#!/usr/bin/env python3
"""Generate the 40 graded cases the prefill A/B eval runs (MYS-2396, MYS-2403).

The eval asks one question: does widening the dynamic prefill to 16-aligned
widths change *answers*, not just tokens? That only means something if

  * every case is real text encoded by the release package's own tokenizer and
    the production chat template (thinking off) -- never hand-written id lists,
    which is what made earlier drivers time out on this board;
  * every case makes the two rules take *different* paths, otherwise the
    comparison has nothing to compare. For a single-shot prompt that means the
    total length is ``16 <= n % 64``: 64-alignment then prefills ``n - n % 64``
    rows and replays the rest, while 16-alignment prefills at least 16 more.
    For a follow-up turn it means the appended chunk is 16..63 tokens, so
    64-alignment replays all of it and 16-alignment runs one dynamic launch;
  * every case has a fixed answer and a case-insensitive regular expression
    that only that answer can satisfy, so grading is mechanical.

Two sets of the same 40 questions:

  ``mid`` (default, ``tools/prefill_ab_cases/*.txt``) -- the MYS-2396 set. It
  deliberately keeps ``n % 64 >= 16`` so that under 64-alignment the exact
  replay tail is at least 16 rows, i.e. wide enough that replaying it is
  affordable. MYS-2403 needs the opposite corner.

  ``low`` (``--set low``, ``tools/prefill_ab_cases/low/*.txt``) -- the same
  questions with the padding re-tuned so that ``n % 64 <= 7`` (and, for a C
  follow-up, ``delta % 64 <= 7``). Under the production rule 64-alignment
  replays only those 0..7 rows, so almost the whole prompt goes through the
  inaccurate prefill graphs -- the corner MYS-2403 asks about.

Three families, 40 cases per set:

  A  short question, 40..250 token prompt, one extractable answer;
  B  a self-written article of 300..1500 tokens plus a question about exactly
     one fact that appears only in the article;
  C  a first turn (article + question + the assistant's answer, <= 2048 tokens)
     prefilled as history, one decode, then a 20..60 token follow-up asking
     about a second fact in the same article.

Lengths are tuned by appending whole sentences from a per-case pool until the
length constraints hold, so padding is more real prose, never filler tokens.
Every file is verified after writing and the manifest half of ``cases.json``
records length + sha256, so the committed ids can be checked without an NPU:

    python3 tools/prefill_ab_cases/gen_cases.py --lib \\
        /opt/sophgo/cv84x6_llm_server/lib/libcv84x6_llm.so \\
        --tokenizer /opt/sophgo/cv84x6_llm_server/model-config/qwen3_5/tokenizer.json

    python3 tools/prefill_ab_cases/gen_cases.py --set low --lib ... --tokenizer ...

    python3 tools/prefill_ab_cases/gen_cases.py --verify            # host test
    python3 tools/prefill_ab_cases/gen_cases.py --set low --verify  # host test
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

HERE = os.path.dirname(os.path.abspath(__file__))
CASES_JSON = os.path.join(HERE, "cases.json")

VOCAB = 248320
MAX_HISTORY = 2048
MIN_FRESH, MAX_FRESH = 40, 250          # A
MIN_ARTICLE, MAX_ARTICLE = 300, 1500    # B
MIN_DELTA, MAX_DELTA = 16, 63           # C follow-up chunk
PREFERRED_DELTA = (36, 60)              # where a dynamic launch beats replay
ALIGN_BASE = 64

# The two sets, described by the window each one keeps its lengths in. The
# window is on ``n % 64`` because that is exactly how many rows 64-alignment
# replays through the exact decode graphs:
#
#   mid  -- 16..63 rows replayed, i.e. the affordable-replay corner MYS-2396
#           compared against align=16 (its follow-up chunks are 16..63 tokens,
#           so 64 alignment replays the whole chunk);
#   low  -- 0..7 rows replayed, i.e. the "almost nothing is exact" corner
#           MYS-2403 asks about (its follow-up chunks are 64..71 tokens, so 64
#           alignment replays only the remainder and one dynamic launch of 64
#           rows goes through the inaccurate prefill graphs).
SETS = {
    "mid": {"dir": HERE, "cases_json": os.path.join(HERE, "cases.json"),
            "rem_min": MIN_DELTA, "rem_max": ALIGN_BASE - 1,
            "delta_min": MIN_DELTA, "delta_max": MAX_DELTA},
    "low": {"dir": os.path.join(HERE, "low"),
            "cases_json": os.path.join(HERE, "low", "cases.json"),
            "rem_min": 0, "rem_max": 7,
            "delta_min": ALIGN_BASE, "delta_max": ALIGN_BASE + 7},
}
SET = "mid"          # selected by --set before anything is generated/verified

# What the template appends for the turn after (app/api/tool_calls.py).
NEXT_TURN = "<|im_end|>\n<|im_start|>user\n"


# --------------------------------------------------------------------------
# The cases
# --------------------------------------------------------------------------
# A: preamble sentences give the prompt enough length to be a real request
# rather than a bare phrase, and the question stays last so the model answers it.
A_PREAMBLE = [
    "I am checking a set of short factual questions and I need the answers to be easy to grade.",
    "Please reply with the value or the name only, without a sentence around it and without explaining how you got it.",
]

A_CASES = [
    ("a01", "How many minutes are there in three and a half hours?", r"\b210\b"),
    ("a02", "What is 47 multiplied by 6?", r"\b282\b"),
    ("a03", "How many metres are there in five kilometres?", r"\b5,?000\b"),
    ("a04", "A train covers 90 kilometres in 1.5 hours. What is its average speed in kilometres per hour?",
     r"\b60\b"),
    ("a05", "How many days are there in a leap year?", r"\b366\b"),
    ("a06", "What is the chemical symbol for silver?", r"\bAg\b"),
    ("a07", "Who wrote the play Romeo and Juliet?", r"Shakespeare"),
    ("a08", "What is the capital city of Australia?", r"Canberra"),
    ("a09", "What is 1024 divided by 8?", r"\b128\b"),
    ("a10", "How many sides does a heptagon have?", r"\b7\b|seven"),
    ("a11", "How many grams are there in 3.5 kilograms?", r"\b3,?500\b"),
    ("a12", "At sea level, at what temperature in degrees Celsius does water boil?",
     r"\b100\b"),
    ("a13", "Which planet orbits closest to the Sun?", r"Mercury"),
    ("a14", "What is 15 percent of 240?", r"\b36\b"),
    ("a15", "How many vertices does a cube have?", r"\b8\b|eight"),
]

# B: each article is self-contained prose; the answer must appear nowhere else,
# and the question is appended after it in the same user message.
B_CASES = [
    ("b01",
     "The Kestrel Bay desalination plant began operating in March after two years of "
     "construction. It draws seawater through an intake pipeline that runs 6.2 kilometres "
     "out into the bay, well beyond the tidal flats where the seagrass beds are protected. "
     "Inside the main hall, six reverse-osmosis trains sit in two rows, each served by its "
     "own high-pressure pump and energy-recovery device.\n\n"
     "Commissioning engineers spent eleven weeks bringing the trains online one at a time, "
     "because the membrane elements need a slow first pressurisation to settle into their "
     "housings. During that period the plant ran at about a fifth of its design output and "
     "sent most of the product water back into the aquifer through a recharge well rather "
     "than into the town supply.\n\n"
     "At full output the plant supplies 38,400 cubic metres of drinking water per day, a "
     "little more than the town and the surrounding farms use in an average winter week. "
     "Output is throttled in summer, not because the plant is limited but because the "
     "receiving reservoir reaches its operating ceiling.\n\n"
     "The brine outfall is diffused across the seabed through a row of small nozzles, and "
     "the monitoring programme samples the sediments twice a year. The last two surveys "
     "found no measurable change in the invertebrate community within fifty metres of the "
     "outfall. A maintenance shutdown is scheduled for the second Tuesday of each month, "
     "when the trains are cleaned and the membranes inspected. The plant employs "
     "twenty-three people, fourteen of them on shift.",
     ["The site was chosen over two alternatives because the bay shelves steeply close to "
      "the shore.",
      "Power for the high-pressure pumps comes from a dedicated feeder that also serves "
      "the wastewater works.",
      "Spare membrane elements are stored in a dry room kept below forty percent humidity."],
     "According to the article above, how many cubic metres of drinking water per day does "
     "the Kestrel Bay plant supply at full output?",
     r"\b38,?400\b"),

    ("b02",
     "The orchard above the village was planted in 1998 on land that had been rough grazing "
     "for most of the previous century. Its first owner kept careful notebooks, and the "
     "current tenants still record every graft and every grubbing in the same format: date, "
     "block, variety, rootstock, and the weather on the day.\n\n"
     "Thirty-four apple varieties grow there now, most of them old local sorts that survive "
     "in only a handful of other places. The Marlowe Pippin covers 12 hectares along the "
     "south-facing slope and is by far the largest planting; nothing else exceeds four "
     "hectares. It crops heavily in alternate years, which the tenants partly correct by "
     "thinning the fruit in June.\n\n"
     "The cider press was bought second-hand in 2004 and rebuilt over one winter. It runs "
     "on a three-phase motor and takes about forty minutes to fill a 1,200-litre tank. "
     "Juice for the shop is pasteurised; juice for cider is left wild, and the fermentation "
     "is followed by gravity rather than by measurement.\n\n"
     "The orchard sells fruit at the gate from September, and the picking teams are paid by "
     "the bin rather than by the hour, which the tenants say is the only arrangement that "
     "survives a wet week.",
     ["The highest block is the last to be picked, sometimes not until the end of October.",
      "A windbreak of alder along the western edge replaced a hedge that was lost to "
      "disease.",
      "Beekeepers bring hives in May and take them away once the blossom has fallen."],
     "According to the article above, which apple variety occupies the largest area of the "
     "orchard?",
     r"Marlowe\s+Pippin"),

    ("b03",
     "The museum's globe arrived in 1961 as part of a bequest from a family that had kept "
     "it in the same room for four generations. It is a celestial globe, not a terrestrial "
     "one, so the constellations are engraved on the outside and the brass meridian ring "
     "carries a degree scale worn smooth where hands have turned it.\n\n"
     "The maker's signature sits inside the horizon ring, partly hidden by the stand: Jonas "
     "Feldkirch, Augsburg, 1587. Feldkirch is known from three other surviving instruments "
     "and from a tax record that lists his workshop in the same street as two other "
     "instrument makers. The globe's gores are paper over plaster, a construction that was "
     "common at the time and that explains why so few of them survive.\n\n"
     "Conservation in 2013 stabilised the paper without replacing it, and the cleaning "
     "removed four hundred years of soot but no original lacquer. The stand is a later "
     "replacement, probably eighteenth century, and is not original to the sphere.\n\n"
     "The globe is displayed at a height that lets visitors see the southern constellations, "
     "which is unusual: most surviving globes of this period are shown from the northern "
     "side, where the engraving is better preserved.",
     ["A small repair to the equator ring was made with brass of a slightly different alloy.",
      "The bequest also included two astrolabes, which are stored rather than displayed.",
      "A facsimile of the gores is available in the reading room for handling."],
     "According to the article above, who made the celestial globe?",
     r"Feldkirch"),

    ("b04",
     "From the first of next month the harbour ferry will leave fifteen minutes earlier on "
     "weekdays. The 07:15 crossing is withdrawn and a 06:50 sailing takes its place, which "
     "the operator says reflects what the passenger counts have shown for two years: the "
     "boat is full by the time it reaches the second stop, and the people who board last "
     "are the ones who work furthest from the terminal.\n\n"
     "The new vessel is the Aldebaran, a catamaran launched last spring and used until now "
     "on the summer timetable only. It carries 220 passengers, takes bicycles on the lower "
     "deck, and crosses in nineteen minutes in anything short of a gale. Its predecessor, "
     "the Coralie, will be kept as a relief boat and taken out of the water each winter.\n\n"
     "Fares are unchanged, but the operator is ending the paper carnet and replacing it with "
     "a tap-on card that can be topped up at the terminal or by phone. Passengers who still "
     "hold unused carnet tickets can exchange them for credit until the end of the year.\n\n"
     "The consultation ran for six weeks and drew 340 responses, most of them about the "
     "earlier departure rather than about the vessel itself.",
     ["The terminal car park will keep its current layout and charges for another year.",
      "Bicycle spaces are limited to thirty on each crossing and cannot be reserved.",
      "The winter timetable is published separately and is not affected by this change."],
     "According to the article above, what is the name of the new ferry?",
     r"Aldebaran"),

    ("b05",
     "The survey vessel worked the shelf break for nine weeks, and the cruise report arrived "
     "this month. It records 47 sampling stations, of which 41 produced complete cores; the "
     "remainder were lost to weather or to the winch. The deepest station reached 3,180 "
     "metres, and the shallowest was in 84 metres of water.\n\n"
     "Two thirds of the stations were occupied twice, once at the start of the cruise and "
     "once at the end, so that the same ground could be compared under different seasons. "
     "The repeat visits showed a clear change in the coarse fraction at the shallower sites "
     "and very little change below about 1,500 metres.\n\n"
     "The chemistry team ran oxygen and nutrient profiles at every station, and the "
     "sediment team took a subsample from the top two centimetres of each core. The cores "
     "themselves are held at four degrees in the shore laboratory and will be subsampled "
     "again next year.\n\n"
     "The ship carried nineteen scientists and a crew of twelve, and the cruise was the "
     "first for the vessel after a refit that replaced the winch and the aft deck "
     "crane.",
     ["Weather stopped work on eleven days, most of them in the second half of the cruise.",
      "A hydrophone was towed for the whole cruise and recorded continuously.",
      "The report recommends a further season of work on the northern part of the shelf."],
     "According to the article above, how many sampling stations did the cruise occupy?",
     r"\b47\b|\bforty[- ]seven\b"),

    ("b06",
     "The bakery on the corner has kept the same sourdough starter since the shop opened "
     "twenty-six years ago. It has a name, Beatrice, which was painted on the crock by the "
     "first baker and has stayed on every crock since. Beatrice is fed twice a day with "
     "stone-ground flour and water, and the bakers say the difference between a good week "
     "and a bad one is nearly always the temperature of the water rather than the flour.\n\n"
     "The shop bakes three breads from it: a country loaf, a seeded loaf, and a rye with "
     "about a third of the rye milled on site. Everything is baked on stone, and the ovens "
     "are loaded by hand with a peel because the door is too narrow for a mechanical "
     "loader.\n\n"
     "The crock itself is glazed stoneware with a loose lid, and the starter is kept at "
     "about 22 degrees overnight in summer and in a cooler corner in winter. When the shop "
     "closes for its annual fortnight, the starter goes home with one of the bakers and is "
     "fed on the same schedule, because a neglected starter takes weeks to come back.\n\n"
     "There are four bakers, all of whom start at four in the morning, and the shop sells "
     "out before eleven on most Saturdays.",
     ["The flour comes from a mill two hours away and is delivered on Tuesdays.",
      "A second, stiffer starter is kept for the rye and is refreshed weekly.",
      "The bakehouse was a greengrocer's before the shop took it over."],
     "According to the article above, what is the name of the bakery's sourdough starter?",
     r"Beatrice"),

    ("b07",
     "The new telescope on the ridge has a 4.1-metre primary mirror made of eighteen "
     "hexagonal segments, each of which is held on three actuators and figured to a "
     "fraction of a wavelength. The site sits at 2,640 metres on the edge of the dry "
     "plateau, where the median seeing is under an arcsecond and the cloud cover in the "
     "observing season is close to zero.\n\n"
     "The mirror was polished over three years. Two of the segments had to be re-figured "
     "after the first interferometric test showed an edge roll that the polishing model had "
     "not predicted. The coating chamber on site can re-aluminise a segment in a day, and "
     "the plan is to recoat the whole array every eighteen months.\n\n"
     "First light is scheduled for the end of next year, with the commissioning instrument "
     "being a wide-field camera rather than a spectrograph. The telescope will be operated "
     "remotely, with two staff on the mountain at any time and the rest of the team working "
     "from the city.\n\n"
     "The dome is a calotte design, which keeps the building small and the seeing inside it "
     "stable, but the vents have to be opened well before sunset or the mirror takes hours "
     "to reach ambient temperature.",
     ["A seeing monitor runs continuously at the site and posts its data publicly.",
      "The access road was widened for the transport of the mirror cell.",
      "The telescope's secondary is supported by a hexapod rather than a spider."],
     "According to the article above, what is the diameter of the telescope's primary "
     "mirror, in metres?",
     r"\b4\.1\b|four point one"),

    ("b08",
     "The library's digitisation programme has passed 8,900 manuscripts, which the staff "
     "believe is a little over half of the collection they intend to photograph. The work "
     "is paid for by the Halden Trust, whose grant runs for another four years and covers "
     "two camera operators, a conservator, and the servers.\n\n"
     "Each manuscript is photographed on a copy stand with a book cradle that supports the "
     "spine at no more than a hundred degrees, and the conservator has the authority to "
     "stop the work if a binding cannot take the opening. About three percent of the "
     "collection has been set aside for that reason.\n\n"
     "The files are stored as uncompressed TIFFs on a mirrored pair of disks, with a copy "
     "sent to the national archive every quarter. The catalogue records are linked to the "
     "images by shelfmark, and a reader who finds an entry online can order a high "
     "resolution copy at cost.\n\n"
     "The oldest item photographed so far is a twelfth-century psalter; the most used is a "
     "nineteenth-century ledger of the town's water company, which is requested by family "
     "historians almost every week.",
     ["The equipment was upgraded twice, once for the cameras and once for the lighting.",
      "Volunteers transcribe the catalogue entries, and their work is checked by staff.",
      "A small exhibition of facsimiles opened in the reading room this spring."],
     "According to the article above, which trust funds the digitisation programme?",
     r"Halden"),

    ("b09",
     "The cooperative brought in 6,400 tonnes of grapes this year, which is close to the "
     "five-year average and a relief after two short harvests. Picking began on 12 "
     "September in the warmest parcels and finished on 4 October after a day of rain that "
     "stopped work for a shift and a half.\n\n"
     "Members deliver to the press house in 400-kilogram bins, and each delivery is "
     "weighed and sampled before it is tipped. The must is fermented in stainless steel for "
     "the whites and in a mix of steel and old oak for the reds; the cooperative has never "
     "bought a new barrel, which the winemaker describes as a policy rather than an "
     "accident.\n\n"
     "The harvest is paid for by a formula that combines quantity with a measure of "
     "quality, so a member with low yields and ripe fruit does better per kilogram than one "
     "who simply picks a lot. The formula is reviewed every three years and has survived "
     "two attempts to replace it.\n\n"
     "Bottling runs from February, and most of the output leaves in tanker for the "
     "supermarket own-brand trade; about a fifth is bottled under the cooperative's own "
     "label.",
     ["The press house was extended in 2016 and has run at capacity in three of the years "
      "since.",
      "A weather station in the highest parcel records temperature and humidity every "
      "fifteen minutes.",
      "The cooperative employs a seasonal team of about sixty people for the harvest."],
     "According to the article above, how many tonnes of grapes did the cooperative bring "
     "in this year?",
     r"\b6,?400\b"),

    ("b10",
     "The mill's weaving shed reopened this summer after four years of repair. The looms "
     "are the originals, built by Fairweather and Sons in 1911 and sold to the mill in the "
     "same year. Sixteen of the original forty survive, and twelve of those run; the others "
     "are kept as a source of parts, which is the only reason the working set has stayed "
     "working.\n\n"
     "The shed roof was replaced first, because water had been getting into the line "
     "shafting for decades. The shafting itself was cleaned and re-bushed rather than "
     "replaced, and the line shaft is still driven by an electric motor through the "
     "original belt, which the volunteers say is quieter than the modern alternative and no "
     "less reliable.\n\n"
     "Weaving demonstrations run twice a week in the season and produce a narrow cotton "
     "cloth that is sold in the shop. The cloth is not competitive with anything; it exists "
     "so that the looms are exercised, because a loom that stands still seizes.\n\n"
     "The mill's archive, which includes the order books from 1908 onwards, is held by the "
     "county record office and has been catalogued down to item level.",
     ["The chimney was repointed at the same time as the roof and is no longer used.",
      "Two of the working looms are warped for a twill and the rest for plain weave.",
      "Volunteer training takes a full season before a new weaver works unsupervised."],
     "According to the article above, which company built the mill's looms?",
     r"Fairweather"),

    ("b11",
     "The reserve covers 1,240 hectares of wet meadow, reedbed, and a strip of alder "
     "carr along the river. It was bought by the trust in 1974, when drainage proposals "
     "threatened the whole valley, and has been managed for waders ever since.\n\n"
     "The reserve's first warden was Ines Kalda, who arrived from a coastal site with a "
     "reputation for being able to count breeding lapwing from a moving vehicle. She wrote "
     "the management plan that is still, in outline, the one in use: late cutting, high "
     "water in winter, and no fertiliser anywhere on the site.\n\n"
     "The lapwing numbers rose for a decade and then flattened, which the present warden "
     "attributes to predation rather than to habitat. Electric fencing went up around two "
     "of the wet fields three years ago; the effect on hatching success has been measurable "
     "but modest.\n\n"
     "Visitors are kept to a marked route between April and July, and the hides are open "
     "all year. The reserve has no visitor centre, and the trust has decided against "
     "building one, on the grounds that the car park is the constraint rather than the "
     "building.",
     ["The river was re-meandered along two hundred metres of straightened channel in 2009.",
      "Grazing is by a small herd of native cattle, rented in for the summer.",
      "The reserve's moth records go back to the 1980s and are the best in the county."],
     "According to the article above, who was the reserve's first warden?",
     r"Kalda"),

    ("b12",
     "The migration off the legacy system finished in one weekend, after eighteen months of "
     "preparation and three full rehearsals. The old system, Grayling, had been in service "
     "since the early nineties and was held together by scheduled jobs whose purpose nobody "
     "could fully explain; the migration team's first task was to work out which of them "
     "actually mattered.\n\n"
     "Eighteen million records moved across, of which about 400,000 were duplicates that "
     "the old system had tolerated and the new one would not. The duplicates were matched "
     "on a combination of surname, date of birth, and postcode, and the ambiguous ones were "
     "referred to a small team rather than resolved automatically.\n\n"
     "The cutover began on a Friday evening and the new system was in use on Monday "
     "morning. The old system was kept readable for six months, in case anything had to be "
     "checked, and then switched off.\n\n"
     "The team's own conclusion is that the rehearsals were what made the weekend dull, and "
     "that dull was the goal.",
     ["A read-only copy of the legacy database is retained for audit purposes.",
      "Two reports were reimplemented from scratch because their original logic was "
      "undocumented.",
      "Training ran for six weeks before the cutover and continued for a month after it."],
     "According to the article above, what was the name of the legacy system that was "
     "replaced?",
     r"Grayling"),

    ("b13",
     "The solar farm on the former airfield was connected in April and has been exporting "
     "since. It uses 21,600 panels on single-axis trackers, arranged in rows that follow the "
     "old taxiway lines, with a capacity of 8.4 megawatts at the point of connection.\n\n"
     "The trackers were chosen over fixed mounting because the site is flat and the "
     "constraint was the connection capacity rather than the land area. The rows are spaced "
     "so that no row shades its neighbour before ten in the morning or after four in the "
     "afternoon at any time of year.\n\n"
     "Sheep graze the site between the rows from May to September, which keeps the grass "
     "down without mowing and, the operator says, has caused no damage to the tracker "
     "bearings in two seasons. The flock is moved in small paddocks so that no area is "
     "grazed hard.\n\n"
     "The site is fenced and monitored, and the inverters report to a control room in the "
     "next county. Output on a clear day peaks a little after midday and the annual total "
     "is expected to be within ten percent of the estimate made before construction.",
     ["The airfield's perimeter track is used as the maintenance route.",
      "A weather station on site measures irradiance and module temperature.",
      "The connection is shared with a battery that was installed at the same time."],
     "According to the article above, what is the capacity of the solar farm, in "
     "megawatts?",
     r"\b8\.4\b|eight point four"),

    ("b14",
     "The expedition spent 41 days on the ice and reached the summit by the long ridge "
     "rather than by the face. Five climbers started from Camp Varga, which sits on a "
     "glacier at 4,300 metres and is named after the surveyor who first mapped the valley; "
     "three reached the top, and the other two turned back at the col when one of them "
     "began to show signs of altitude sickness.\n\n"
     "The weather window was narrow. The team had nine days of usable conditions in the "
     "whole period and used four of them for the push, with the rest spent carrying loads "
     "and waiting. Supplies were cached at two points on the ridge, which is why the push "
     "itself took only four days from the camp.\n\n"
     "The ridge route is longer than the face but much less exposed to serac fall, and the "
     "team's report argues that it should become the standard line for commercial parties "
     "as well. Not everyone agrees; two of the operators who read the draft pointed out "
     "that the ridge has no good place to turn around above the col.\n\n"
     "All five climbers were off the ice by the end of the month, and the caches were "
     "cleared on the way down.",
     ["The team used a satellite link for daily weather calls with a forecasting service.",
      "Two of the fixed ropes were left in place for a later party and have since been "
      "removed.",
      "The report includes a table of every load carried above the col."],
     "According to the article above, what is the name of the expedition's base camp?",
     r"Varga"),

    ("b15",
     "The herbarium holds about 214,000 specimens, of which the great majority are "
     "flowering plants from the county and the rest are a working collection of sedges and "
     "grasses from further afield. The sedge collection is the largest in the region and is "
     "the reason the herbarium is consulted from outside.\n\n"
     "The curator, Priya Raghunathan, came from a university collection and has spent the "
     "last six years databasing the backlog. Every sheet is photographed, and the label "
     "data are transcribed by volunteers and then checked against the specimen itself, "
     "because nineteenth-century labels are frequently wrong about locality.\n\n"
     "The building is kept at a constant humidity, which matters more than temperature; a "
     "dry sheet is a durable sheet, and a damp one is an invitation to beetles. Incoming "
     "material is frozen for a week before it is filed, a practice adopted after an "
     "infestation in the 1990s that took two years to clear.\n\n"
     "Researchers can borrow specimens by post, and the herbarium sends out about sixty "
     "loans a year, most of them to universities studying the same groups.",
     ["The oldest specimen is a pressed orchid collected in 1821.",
      "A duplicate set of common species is kept separately for teaching.",
      "The database is published online and updated every quarter."],
     "According to the article above, who is the curator of the herbarium?",
     r"Raghunathan"),
]

# C: a first turn (article + question + the assistant's answer) becomes the
# prefilled history; the follow-up asks about a second fact in the same article.
C_CASES = [
    ("c01",
     "The tramway extension opened on 3 May after four years of construction and a year of "
     "testing. It adds six stops along the old freight alignment, and the whole line now "
     "runs from the hospital to the university in thirty-one minutes, which is roughly half "
     "the time the same journey takes by bus in the morning peak.\n\n"
     "The project cost 41 million, most of it spent on the two new bridges and on moving "
     "the utilities that ran under the alignment. The depot is at Wexford Lane, on the site "
     "of a former coal yard, and it holds twelve trams with room for four more if the fleet "
     "grows.\n\n"
     "Trams run every eight minutes during the day and every fifteen in the evening. The "
     "vehicles are the same as those on the older section, so the workshops need no new "
     "tooling, which the operator says was a deliberate condition of the purchase.",
     ["The overhead line was renewed along the whole extension rather than only the new "
      "section.",
      "A park-and-ride site at the eastern terminus opened at the same time.",
      "The old freight sheds were demolished, but their gates were kept and re-erected at "
      "the depot."],
     "When did the tramway extension open?",
     "It opened on 3 May, after four years of construction and a year of testing.",
     "Thanks. Where is the new depot, and what used to stand on that site before it was built?",
     r"Wexford"),

    ("c02",
     "The container vessel was delivered to its owner last month and will enter service on "
     "the northern loop once the winter schedule is published. It carries 4,800 containers "
     "and is the first of three sister ships ordered together; the other two follow in the "
     "next eighteen months.\n\n"
     "The ship was built at the Nakai yard, which had not built a vessel of this size "
     "before and took the order on the understanding that the design would be repeated "
     "three times. The hull is wider than the previous class, which improves stability and "
     "lets the deck stow one more tier.\n\n"
     "The crew is twenty-two, of whom six are engine room ratings. The bridge is arranged "
     "for one-person operation at sea, though the owner has said it will keep two officers "
     "on watch until the crew is familiar with the new systems.",
     ["The main engine is a two-stroke running on very low sulphur fuel.",
      "Two of the three ships will be chartered to a partner line for their first year.",
      "Sea trials were completed in nine days, two of which were lost to weather."],
     "How many containers does the ship carry?",
     "It carries 4,800 containers, and it is the first of three sister ships.",
     "Thanks. Which yard built the ship, and had that yard built anything this size before?",
     r"Nakai"),

    ("c03",
     "The new hospital wing opened to patients in February and takes the overflow from the "
     "medical and surgical wards. It has 96 beds, all in single rooms with their own "
     "bathroom, which the trust says was the main reason for the rebuild: the old wards had "
     "four beds to a bay and no way to isolate a patient without closing the bay.\n\n"
     "The wing is named after Dr Aveline Roth, who ran the hospital's anaesthetic "
     "department for nineteen years and who, according to the plaque in the entrance, "
     "insisted that the operating theatres be built with daylight.\n\n"
     "Staffing has been the difficult part. The trust has recruited to about eighty percent "
     "of the planned nursing establishment and is running the wing at reduced occupancy "
     "until the rest is filled, which it expects to take another year.",
     ["The building has a courtyard garden that is open to patients and visitors.",
      "Two of the rooms are fitted for bariatric care and have ceiling hoists.",
      "The old ward block will be converted to outpatient clinics once it is empty."],
     "How many beds does the new wing have?",
     "It has 96 beds, all in single rooms with their own bathroom.",
     "Thanks. Who is the new wing named after, and what did that person do at the hospital?",
     r"Roth"),

    ("c04",
     "The brewery was founded in 1854 and still occupies the same yard, although the "
     "buildings have been rebuilt twice and the oldest part standing now dates from about "
     "1900. It brews four beers regularly and a fifth for the winter, and everything is "
     "cask-conditioned except the bottled version of the bitter.\n\n"
     "The water comes from the Bryn spring, which rises about a kilometre from the yard and "
     "is piped in without treatment other than filtration. The head brewer says the "
     "mineral content is the reason the bitter tastes the way it does, and that when the "
     "brewery briefly used mains water in the 1980s the regular customers noticed within a "
     "fortnight.\n\n"
     "The fermenting room holds eight open squares, and the yeast is repitched for about "
     "ten generations before a fresh culture is brought in from a laboratory in the next "
     "county. The brewery employs eleven people and delivers within a thirty-mile radius "
     "with its own vans.",
     ["The tap room opens on Thursday and Friday evenings.",
      "Marquees are hosted by the brewery in the yard once a year, in June.",
      "The winter beer is a dark mild and is brewed from October."],
     "How many beers does the brewery brew regularly?",
     "It brews four beers regularly, plus a fifth for the winter.",
     "Thanks. Which spring supplies the brewery's water, and does the brewery treat it in any way?",
     r"Bryn"),

    ("c05",
     "The railway bridge over the river was completed in 1878 and carried traffic until the "
     "line closed in 1963. It is 340 metres long and stands on seven wrought-iron spans "
     "carried by stone piers, two of which were rebuilt after a flood in 1912 took out the "
     "upstream cutwater.\n\n"
     "The engineer was Halvard Ness, who is better known for a harbour wall further north "
     "and who was, by the standards of the period, unusually willing to specify ironwork "
     "from more than one foundry so that no single supplier could hold the works to ransom.\n\n"
     "The bridge is now a foot and cycle path, and the deck was resurfaced in 2015. The "
     "spans were shot-blasted and repainted at the same time, and the paint system is "
     "inspected every five years.",
     ["The signal box at the eastern end survives and is listed.",
      "One span was temporarily supported while the pier below it was repointed.",
      "The path forms part of a long-distance route that crosses the river twice."],
     "What is the length of the bridge in metres?",
     "It is 340 metres long, standing on seven wrought-iron spans.",
     "Thanks. Who was the engineer who designed the bridge, and what else is that person known for?",
     r"Ness"),

    ("c06",
     "The botanical garden's palm house was restored over three years and reopened in 2011. "
     "The restoration was paid for by the Ostrowski Foundation, which had previously funded "
     "the rock garden and the library, and which asked only that the work be documented and "
     "the drawings published.\n\n"
     "The glasshouse is a Victorian iron and glass structure with a curved roof and a "
     "central aisle, and the restoration replaced about a third of the glazing bars with "
     "new castings made from the original patterns. The heating was replaced with a system "
     "that runs at a lower temperature and can be zoned, which has cut the fuel bill by "
     "roughly a third.\n\n"
     "The planting is arranged by region rather than by family, and the fern collection in "
     "the north end is the reason many visitors come. The garden employs six horticulturists "
     "and about forty volunteers.",
     ["Entry to the glasshouses is free, and the garden is funded by the trust and by "
      "donations.",
      "The original ventilation gear was kept and is still operated by hand.",
      "A propagation house behind the palm house is not open to the public."],
     "When did the restored palm house reopen?",
     "It reopened in 2011, after a three-year restoration.",
     "Thanks. Which foundation paid for the restoration, and what did it ask for in return?",
     r"Ostrowski"),

    ("c07",
     "The fish market was rebuilt in 1997 on the same quay as its predecessor, and the "
     "architect was Lena Okafor, whose roof of laminated timber is the reason the building "
     "is now photographed more often than it is used. The stalls are let by the day, and "
     "the auction moved out to the industrial estate long before the rebuild.\n\n"
     "The roof spans eighteen metres without intermediate support, which keeps the floor "
     "clear for stalls and for the crowd that arrives on Saturday mornings. The timber was "
     "treated against salt and is inspected annually; two of the beams were replaced after "
     "a leak in 2009.\n\n"
     "The building is open six days a week, and the fishmongers who trade there are mostly "
     "the same families that traded in the old market. The upper floor is let as offices to "
     "the harbour authority.",
     ["The quay outside was raised in 2004 to reduce flooding at spring tides.",
      "A small display about the old market stands at the eastern entrance.",
      "The market closes for two days each January for maintenance."],
     "In which year was the fish market rebuilt?",
     "It was rebuilt in 1997 on the same quay as its predecessor.",
     "Thanks. Who designed the market's roof, and what is unusual about the way it spans the floor?",
     r"Okafor"),

    ("c08",
     "The radio telescope array on the Karoo plateau has been taking data for two years with "
     "24 dishes, and the plan is to double that number before the end of the decade. The "
     "site was chosen for its radio quietness, which is protected by law within a radius of "
     "a hundred kilometres, and for the flat ground, which makes the foundations cheap.\n\n"
     "Each dish is seven metres across and is connected to the correlator by buried fibre. "
     "The array observes in two bands and can split its dishes between them, which the "
     "project scientist says is the single most useful feature of the design.\n\n"
     "The data rate is high enough that the raw voltages are not kept; the correlator "
     "reduces them to visibilities, and those are archived and released after an embargo of "
     "eighteen months. About forty people work on site, and the nearest town is an hour away "
     "by road.",
     ["The site has its own weather station and a diesel generator for backup.",
      "A test dish was built two years before the first production dish.",
      "The correlator building is cooled by outside air for most of the year."],
     "How many dishes does the array currently have?",
     "It currently has 24 dishes, with a plan to double that number.",
     "Thanks. On which plateau is the array built, and why was that particular site chosen?",
     r"Karoo"),

    ("c09",
     "The paper mill closed in 2009 after a century of operation, and the site has been "
     "partly cleared since. At its peak it employed 210 people, and the last machine to run "
     "was the Brunhild, which had been rebuilt twice and was, by the end, producing paper "
     "for the local newspaper trade.\n\n"
     "The mill drew its water from the river and returned it, after treatment, a little "
     "warmer. The weir that fed the turbine is still in place and now generates a small "
     "amount of electricity for the site's remaining buildings, which are let to small "
     "businesses.\n\n"
     "A local history group has recorded interviews with about sixty former workers, and "
     "the recordings are held by the county archive. The group is also collecting machine "
     "plates and other small items that were salvaged when the machinery was scrapped.",
     ["The chimney was demolished in 2014 after a survey found it unsafe.",
      "The mill's railway siding has been lifted and is now a footpath.",
      "Two of the warehouse buildings are listed and cannot be altered."],
     "How many people did the mill employ at its peak?",
     "It employed 210 people at its peak, before it closed in 2009.",
     "Thanks. What was the name of the last machine to run, and what did it produce by the end?",
     r"Brunhild"),

    ("c10",
     "The mountain hut was built in 1928 by a climbing club and has been staffed every "
     "summer since, except for two years during the war. It stands at 2,780 metres on a "
     "shoulder below the main ridge, and the view from the terrace takes in three valleys "
     "and, on a clear day, the sea.\n\n"
     "The hut has been kept by the Bregoli family for three generations; the present "
     "custodian is the grandson of the first, and his children carry supplies up in summer. "
     "Everything that cannot be walked in is flown in by helicopter twice a season, which "
     "is expensive and, the custodian says, the reason the menu is short.\n\n"
     "There are 46 beds in dormitories and a further 12 in two small rooms, and the kitchen "
     "serves one sitting at seven. Water comes from a spring above the hut and is stored in "
     "a tank under the terrace.",
     ["The hut is closed from the end of September to the middle of June.",
      "A meteorological station on the roof reports temperature and wind to the club.",
      "The original stove was replaced in 1987 but kept as a display."],
     "How many beds does the hut have in total?",
     "It has 58 beds in total, 46 in dormitories and 12 in two small rooms.",
     "Thanks. Which family has kept the hut for three generations, and who is the custodian now?",
     r"Bregoli"),
]


# --------------------------------------------------------------------------
# Tokenizer (same ctypes path the release package uses on the board)
# --------------------------------------------------------------------------
def bind(lib_path: str) -> ctypes.CDLL:
    lib = ctypes.CDLL(lib_path)
    err = ctypes.POINTER(ctypes.c_char_p)
    lib.llm_tokenizer_load.restype = ctypes.c_void_p
    lib.llm_tokenizer_load.argtypes = [ctypes.c_char_p, err]
    lib.llm_tokenizer_free.argtypes = [ctypes.c_void_p]
    lib.llm_tokenizer_encode.restype = ctypes.c_int
    lib.llm_tokenizer_encode.argtypes = [ctypes.c_void_p, ctypes.c_char_p,
                                        ctypes.POINTER(ctypes.c_int), ctypes.c_int, err]
    lib.llm_tokenizer_vocab_size.restype = ctypes.c_int
    lib.llm_tokenizer_vocab_size.argtypes = [ctypes.c_void_p]
    return lib


class Tokenizer:
    def __init__(self, lib: ctypes.CDLL, path: str):
        self.lib = lib
        self.err = ctypes.c_char_p()
        self.h = lib.llm_tokenizer_load(path.encode(), ctypes.byref(self.err))
        if not self.h:
            raise SystemExit(f"tokenizer_load: {self.err.value}")

    def encode(self, text: str) -> list[int]:
        raw = text.encode("utf-8")
        n = self.lib.llm_tokenizer_encode(self.h, raw, None, 0,
                                          ctypes.byref(self.err))
        if n < 0:
            raise SystemExit(f"encode: {self.err.value}")
        buf = (ctypes.c_int * max(n, 1))()
        got = self.lib.llm_tokenizer_encode(self.h, raw, buf, n,
                                            ctypes.byref(self.err))
        if got != n:
            raise SystemExit(f"encode: asked for {n}, wrote {got}")
        return list(buf)[:n]

    def close(self) -> None:
        if self.h:
            self.lib.llm_tokenizer_free(self.h)
            self.h = None


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------
class Msg:
    """Just enough of the API's ChatMessage for the renderer, which reads
    ``.role`` / ``.content`` / ``.reasoning_content`` / ``.tool_calls``."""

    def __init__(self, role: str, content: str):
        self.role = role
        self.content = content
        self.reasoning_content = ""
        self.tool_calls = None


def render(messages: list) -> str:
    from app.api.tool_calls import render_messages
    return render_messages(messages)[0]   # enable_thinking=False: production default


def generating_header() -> str:
    """The template's generating header, thinking off."""
    from app.api.tool_calls import THINK_CLOSE, THINK_OPEN
    return f"<|im_start|>assistant\n{THINK_OPEN}\n\n{THINK_CLOSE}\n\n"


def set_dir() -> str:
    """Directory holding the selected set's id files and cases.json."""
    return SETS[SET]["dir"]


def separates(n: int) -> bool:
    """Does this single-shot prompt length sit in the selected set's window?

    The window is on ``n % 64``, the number of rows 64-alignment replays exactly:
    ``mid`` wants 16..63 (MYS-2396's affordable-replay corner), ``low`` wants
    0..7 (MYS-2403's "almost nothing is exact" corner).
    """
    cfg = SETS[SET]
    return cfg["rem_min"] <= n % ALIGN_BASE <= cfg["rem_max"]


def separates_delta(nd: int) -> bool:
    """The same question for a C follow-up chunk.

    ``mid``: the chunk is 16..63 tokens, so 64 alignment replays all of it one
    row at a time while 16 alignment runs a single dynamic launch.

    ``low``: the chunk is 64..71 tokens, so 64 alignment replays only the 0..7
    row remainder and lets a 64-row dynamic launch through the inaccurate
    prefill graphs -- the same corner as a low single-shot prompt.
    """
    cfg = SETS[SET]
    return cfg["delta_min"] <= nd <= cfg["delta_max"]


def describe_set() -> str:
    cfg = SETS[SET]
    return (f"n%64 in {cfg['rem_min']}..{cfg['rem_max']}, follow-up "
            f"{cfg['delta_min']}..{cfg['delta_max']} tokens")


def describe_set_doc() -> dict:
    cfg = SETS[SET]
    if SET == "mid":
        note = ("A/B: prompt must be 16 <= n%64 so the two alignments pick different "
                "widths. C: the appended follow-up chunk must be 16..63 tokens for "
                "the same reason.")
    else:
        note = ("A/B: prompt must be n%64 <= 7, so under 64 alignment only 0..7 rows "
                "are replayed through the exact decode graphs. C: the appended "
                "follow-up chunk must be 64..71 tokens, i.e. delta%64 <= 7.")
    return {"rem_min": cfg["rem_min"], "rem_max": cfg["rem_max"],
            "delta_min": cfg["delta_min"], "delta_max": cfg["delta_max"],
            "note": note}


# --------------------------------------------------------------------------
# Building one case
# --------------------------------------------------------------------------
def tune(make_text, extras, ok, what: str):
    """First prefix of `extras` whose encoding satisfies `ok`; `ok` takes the
    token count. Extras are whole sentences, so the prompt stays real prose."""
    for k in range(len(extras) + 1):
        text = make_text(extras[:k])
        ids = ENC.encode(text)
        if ok(len(ids)):
            return text, ids
    raise SystemExit(f"{what}: no prefix of {len(extras)} extra sentences lands "
                     f"in the required token range")


def write_ids(name: str, ids: list[int]) -> dict:
    raw = ",".join(str(i) for i in ids) + "\n"
    with open(os.path.join(set_dir(), name), "w", encoding="utf-8") as f:
        f.write(raw)
    print(f"{name}: {len(ids)} ids", flush=True)
    return {"ids_file": name, "tokens": len(ids),
            "sha256": hashlib.sha256(raw.encode()).hexdigest()}


def build_a(case_id: str, question: str, match: str) -> dict:
    def make(extra: list[str]) -> str:
        return " ".join(A_PREAMBLE + extra) + "\n\n" + question

    text, ids = tune(make, pad_pool(A_QUESTION_PAD),
                     lambda n: MIN_FRESH <= n <= MAX_FRESH and separates(n), case_id)
    return {"id": case_id, "type": "A", "question": question, "match": match,
            "text": text, **write_ids(f"{case_id}.txt", ids)}


def build_b(case_id: str, article: str, extra: list[str], question: str,
            match: str) -> dict:
    def make(pad: list[str]) -> str:
        body = article + "".join("\n\n" + s for s in pad)
        return body + "\n\n" + question

    text, ids = tune(make, pad_pool(extra + GENERIC_PAD),
                     lambda n: MIN_ARTICLE <= n <= MAX_ARTICLE and separates(n), case_id)
    assert question in text
    return {"id": case_id, "type": "B", "question": question, "match": match,
            "text": text, **write_ids(f"{case_id}.txt", ids)}


def build_c(case_id: str, article: str, extra: list[str], q1: str, a1: str,
            q2: str, match: str) -> dict:
    """History is turn 1 (user + assistant + generating header); the delta is
    exactly what the template appends for turn 2.

    Both are cut out of one render of the three-message conversation, so the
    assistant turn is rendered with the template's own rule (no think block for
    a turn that is no longer the last question) instead of being hand-written.
    """
    pads = C_PAD[SET]
    hist: dict = {}
    for pad in pads:
        for k in range(len(pad) + 1):
            follow = q2 + "".join(" " + s for s in pad[:k])
            full = render([Msg("user", f"{article}\n\n{q1}"), Msg("assistant", a1),
                           Msg("user", follow)])
            i = full.rindex(NEXT_TURN)
            history_text = full[:i] + "<|im_end|>\n" + generating_header()
            delta_text = full[i:]
            history_ids, delta_ids = ENC.encode(history_text), ENC.encode(delta_text)
            if not separates_delta(len(delta_ids)):
                continue
            # Prefer the range where phase 1 measured the dynamic launch as
            # actually cheaper than replay (a 17-row extend was slower). Only
            # the mid set can afford that preference: under 64 alignment a low
            # follow-up is replayed almost entirely whatever its length, so the
            # first phrasing that satisfies the card's window is kept as is.
            if SET == "mid" and not (PREFERRED_DELTA[0] <= len(delta_ids)
                                    <= PREFERRED_DELTA[1]) and hist:
                continue
            hist = {"history_text": history_text, "delta_text": delta_text,
                    "history_ids": history_ids, "delta_ids": delta_ids, "q2": follow}
            break
        if hist:
            break
    if not hist:
        raise SystemExit(f"{case_id}: no follow-up length lands in the {SET} set's "
                         f"window ({describe_set()})")
    if len(hist["history_ids"]) > MAX_HISTORY:
        raise SystemExit(f"{case_id}: history of {len(hist['history_ids'])} tokens "
                         f"exceeds {MAX_HISTORY}")
    if not hist["delta_text"].startswith(NEXT_TURN):
        raise SystemExit(f"{case_id}: the appended chunk lost the template's opener")
    out = {"id": case_id, "type": "C", "question": hist["q2"], "match": match,
           "text": hist["history_text"] + hist["delta_text"]}
    meta = write_ids(f"{case_id}-history.txt", hist["history_ids"])
    out["history_ids_file"] = meta["ids_file"]
    out["history_tokens"] = meta["tokens"]
    out["history_sha256"] = meta["sha256"]
    meta = write_ids(f"{case_id}-delta.txt", hist["delta_ids"])
    out["delta_ids_file"] = meta["ids_file"]
    out["delta_tokens"] = meta["tokens"]
    out["delta_sha256"] = meta["sha256"]
    return out


# --------------------------------------------------------------------------
# Verification (no tokenizer, no NPU)
# --------------------------------------------------------------------------
def read_ids(name: str) -> list[int]:
    with open(os.path.join(set_dir(), name), encoding="utf-8") as f:
        return [int(x) for x in f.read().replace("\n", ",").split(",") if x.strip()]


def _sha(name: str) -> str:
    with open(os.path.join(set_dir(), name), encoding="utf-8") as f:
        return hashlib.sha256(f.read().encode()).hexdigest()


def check_case(c: dict) -> list[str]:
    bad: list[str] = []
    kind = c.get("type")
    if kind in ("A", "B"):
        n = c["tokens"]
        if len(read_ids(c["ids_file"])) != n:
            bad.append(f"{c['id']}: id file length differs from cases.json")
        if _sha(c["ids_file"]) != c["sha256"]:
            bad.append(f"{c['id']}: id file sha256 differs from cases.json")
        if not separates(n):
            bad.append(f"{c['id']}: n_prompt={n} has n%64={n % ALIGN_BASE}, outside the "
                       f"{SET} set's window ({describe_set()})")
        lo, hi = (MIN_FRESH, MAX_FRESH) if kind == "A" else (MIN_ARTICLE, MAX_ARTICLE)
        if not lo <= n <= hi:
            bad.append(f"{c['id']}: n_prompt={n} outside [{lo}, {hi}]")
        names = [c["ids_file"]]
    elif kind == "C":
        nh, nd = c["history_tokens"], c["delta_tokens"]
        if len(read_ids(c["history_ids_file"])) != nh:
            bad.append(f"{c['id']}: history id file length differs from cases.json")
        if _sha(c["history_ids_file"]) != c["history_sha256"]:
            bad.append(f"{c['id']}: history id file sha256 differs from cases.json")
        if len(read_ids(c["delta_ids_file"])) != nd:
            bad.append(f"{c['id']}: delta id file length differs from cases.json")
        if _sha(c["delta_ids_file"]) != c["delta_sha256"]:
            bad.append(f"{c['id']}: delta id file sha256 differs from cases.json")
        if not separates_delta(nd):
            bad.append(f"{c['id']}: follow-up chunk of {nd} tokens is outside the "
                       f"{SET} set's window ({describe_set()})")
        if nh > MAX_HISTORY:
            bad.append(f"{c['id']}: history of {nh} tokens exceeds {MAX_HISTORY}")
        names = [c["history_ids_file"], c["delta_ids_file"]]
    else:
        return [f"{c.get('id')}: unknown type {kind!r}"]

    for name in names:
        ids = read_ids(name)
        if not ids:
            bad.append(f"{name}: empty")
        elif min(ids) < 0 or max(ids) >= VOCAB:
            bad.append(f"{name}: ids outside the vocabulary [0, {VOCAB})")
    if not c.get("match"):
        bad.append(f"{c['id']}: no grading pattern")
    return bad


def verify() -> int:
    cfg = SETS[SET]
    with open(cfg["cases_json"], encoding="utf-8") as f:
        doc = json.load(f)
    cases = doc["cases"]
    bad: list[str] = []
    counts = {"A": 0, "B": 0, "C": 0}
    for c in cases:
        counts[c.get("type")] = counts.get(c.get("type"), 0) + 1
        bad += check_case(c)
    if len(cases) != 40:
        bad.append(f"{len(cases)} cases, expected 40")
    if counts != {"A": 15, "B": 15, "C": 10}:
        bad.append(f"case mix {counts}, expected A=15 B=15 C=10")
    on_disk = {n for n in os.listdir(set_dir()) if n.endswith(".txt")}
    listed = set()
    for c in cases:
        listed |= ({c["ids_file"]} if c["type"] != "C"
                   else {c["history_ids_file"], c["delta_ids_file"]})
    if on_disk != listed:
        bad.append(f"id files on disk differ from cases.json "
                   f"(+{sorted(on_disk - listed)} -{sorted(listed - on_disk)})")
    for line in bad:
        print(line)
    print(f"[{SET}] {len(cases)} cases ({counts['A']} A / {counts['B']} B / "
          f"{counts['C']} C), {len(bad)} problems")
    return 0 if not bad else 1


# Extra sentences used to tune A prompts into their length band without
# changing what is asked.
A_QUESTION_PAD = [
    "The answer only needs to be right, not explained.",
    "If the question has a numeric answer, give it in digits.",
    "Do not add units unless the question asks for them.",
    "This is one of a set of forty questions and each is graded on its own.",
    "Please answer now.",
]

# Neutral sentences appended after a B article when its own extra sentences
# cannot reach the length its set needs. Real prose, and free of every answer in
# the set, so a case never grades itself.
GENERIC_PAD = [
    "The records for the period were checked before the report was circulated.",
    "A full set of working papers is kept with the archive copy.",
    "The figures quoted here were reviewed twice before publication.",
    "Anyone who wants the underlying data can ask the office for it.",
    "The account was written in the order the work was done.",
    "Minor corrections were made after the first draft was read.",
    "Nothing in this description has been changed since it was filed.",
    "A short summary appears at the end of the file.",
]

# Candidate sentences shared by both sets. The mid set reaches its window
# (n%64 >= 16) with the A_QUESTION_PAD/GENERIC_PAD wording alone; the low set
# needs a finer-grained knob because it is chasing a 8-wide remainder window out
# of 64. Each phrasing below is a different token length, so a prefix of this
# pool moves the length by 1-3 tokens at a time and lands inside 0..7.
SHORT_PAD = [
    "Answer briefly.",
    "Keep it short.",
    "No explanation needed.",
    "Just the answer.",
    "One word will do.",
    "Answer in a word.",
    "Give the answer only.",
    "Be brief.",
    "State it plainly.",
    "Reply with one word.",
    "No working needed.",
    "Answer directly.",
    "A single word is enough.",
    "Keep the reply minimal.",
    "Skip the explanation.",
]

# A C follow-up has to land in the set's window; these keep a short question
# inside it without changing what it asks.
C_PAD = {
    # 16..63 tokens: 64 alignment replays the whole chunk, 16 alignment runs one
    # dynamic launch. One ascending prefix of the four polite sentences.
    "mid": [[
        "Answer with the name only.",
        "Please keep the answer to a single name.",
        "One word is enough for this one.",
        "Give the name and nothing else.",
    ]],
    # 64..71 tokens: 64 alignment replays only the 0..7 row remainder and sends a
    # 64-row dynamic launch through the approximate prefill graphs. A prefix of
    # this pool walks the chunk up through that window.
    "low": [[
        "Answer with the name only.",
        "Please keep the answer to a single name.",
        "One word is enough for this one.",
        "Give the name and nothing else.",
        "Do not explain how you found it.",
        "A single word or a short phrase will do.",
        "No explanation is needed here.",
        "Just name it.",
        "Keep it to one name.",
        "Please be brief.",
    ]],
}


def pad_pool(curated: list[str]) -> list[str]:
    """The sentences available to tune one length, in a fixed order.

    The mid set keeps exactly the pool it was generated with, so its committed
    id files stay byte-identical. The low set appends SHORT_PAD: it is the set
    that has to hit a narrow remainder window, and those extra phrasings are
    what make that reachable without touching the question.
    """
    return list(curated) if SET == "mid" else list(curated) + SHORT_PAD

ENC: Tokenizer | None = None


def main() -> int:
    global SET
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--lib", help="path to libcv84x6_llm.so")
    ap.add_argument("--tokenizer", help="path to the model's tokenizer.json")
    ap.add_argument("--set", dest="which", choices=sorted(SETS), default="mid",
                    help="which case set to generate/verify: mid (MYS-2396, "
                         "n%%64 in 16..63) or low (MYS-2403, n%%64 in 0..7)")
    ap.add_argument("--verify", action="store_true",
                    help="check the committed id files against cases.json only")
    a = ap.parse_args()
    SET = a.which
    if a.verify:
        return verify()
    if not a.lib or not a.tokenizer:
        ap.error("--lib and --tokenizer are required to regenerate")

    os.makedirs(set_dir(), exist_ok=True)
    lib = bind(a.lib)
    globals()["ENC"] = Tokenizer(lib, a.tokenizer)
    try:
        print(f"vocab={lib.llm_tokenizer_vocab_size(ENC.h)} set={SET}", flush=True)
        cases = []
        for cid, question, match in A_CASES:
            cases.append(build_a(cid, question, match))
        for cid, article, extra, question, match in B_CASES:
            cases.append(build_b(cid, article, extra, question, match))
        for (cid, article, extra, q1, a1, q2, match) in C_CASES:
            cases.append(build_c(cid, article, extra, q1, a1, q2, match))
    finally:
        ENC.close()

    doc = {"generator": "tools/prefill_ab_cases/gen_cases.py",
           "set": SET, "align_base": ALIGN_BASE, "min_delta": MIN_DELTA,
           "max_history": MAX_HISTORY, "vocab": VOCAB,
           **describe_set_doc(),
           "cases": sorted(cases, key=lambda c: c["id"])}
    path = SETS[SET]["cases_json"]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")
    print(f"wrote {path}")
    return verify()


if __name__ == "__main__":
    sys.exit(main())
