CC = gcc
CFLAGS = -Wall -Wextra -std=c11 -O3 -g -I/opt/sophon/libsophon-current/include -I./ \
-D USE_GDMA_WITH_CORE=$(USE_GDMA_WITH_CORE)
LDFLAGS = -L/opt/sophon/libsophon-current/lib -lbmlib -lpthread -ldl
TARGET = memtest_gdma
SRCS = memtest_gdma.c
OBJS = $(SRCS:.c=.o)

.PHONY: all clean

all: $(TARGET)

$(TARGET): $(OBJS)
	$(CC) $(CFLAGS) -o $@ $^ $(LDFLAGS)

%.o: %.c
	$(CC) $(CFLAGS) -c -o $@ $<

clean:
	rm -f $(TARGET) *.o