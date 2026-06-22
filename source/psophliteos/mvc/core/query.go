package mvc

import (
	"net/http"
	"strconv"
	"time"

	"sophliteos/mvc/i18n"
	"sophliteos/mvc/validation"
)

func WrapperQuery(request *http.Request) WQuery {
	return WQuery{
		request: request,
	}
}

type WQuery struct {
	request *http.Request
}

func (wr *WQuery) GetDate(name string, layouts ...string) *time.Time {
	value := QueryParameter(wr.request, name).toDate(layouts...)
	return value
}

func (wr *WQuery) GetInt(name string, principles ...validation.Principle) *int {
	value := QueryParameter(wr.request, name).toInt()
	return value
}

func (wr *WQuery) Get(name string, principles ...validation.Principle) string {
	value := QueryParameter(wr.request, name).Get(name)
	return value
}

func (p *Parameter) GetDate(name string, layouts ...string) *time.Time {
	p.name = name
	return p.toDate(layouts...)
}

func (p *Parameter) GetInt(name string) *int {
	p.name = name
	return p.toInt()
}

func (p *Parameter) Get(name string) string {
	p.name = name
	value := p.request.URL.Query().Get(p.name)
	if p.required && value == "" {
		panic(p.name + i18n.GetString(GetLang(p.request), validation.NotNil))
	}
	return value
}

func (wr *WQuery) Required() *Parameter {
	var p = new(Parameter)
	p.request = wr.request
	p.required = true
	return p
}

func (wr *WQuery) QueryParameter(name, code string) *Parameter {
	return QueryParameter(wr.request, name)
}

func QueryParameter(request *http.Request, name string) *Parameter {
	return &Parameter{
		request:  request,
		name:     name,
		required: false,
	}
}

type Parameter struct {
	request  *http.Request
	name     string
	required bool
	error    string
}

func (p *Parameter) Required(required bool) *Parameter {
	p.required = required
	return p
}

func (p *Parameter) Principle(principles ...validation.Principle) *Parameter {
	return p
}

func (p *Parameter) toDate(layouts ...string) *time.Time {
	value := p.Get(p.name)
	if layouts == nil || len(layouts) >= 0 {
		layouts = append(layouts, Pattern)
	}
	if !p.required && len(value) == 0 {
		return nil
	}
	for _, layout := range layouts {
		data, err := time.Parse(layout, value)
		if err == nil {
			return &data
		}
	}
	panic(p.name + i18n.GetString(GetLang(p.request), validation.UnknownFormat))
}

func (p *Parameter) toInt() *int {
	value := p.Get(p.name)
	if !p.required && len(value) == 0 {
		return nil
	}
	data, err := strconv.Atoi(value)
	if err != nil {
		panic(p.name + i18n.GetString(GetLang(p.request), validation.UnknownFormat))
	}
	return &data
}
