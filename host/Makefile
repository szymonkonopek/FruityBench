# Host harness for FruitBench's screen -- builds the platform-free C against a
# simulated recorder so the layout can be checked without a watch.
CC      ?= cc
CSTD    ?= -std=c11
WARN    ?= -Wall -Wextra
INC     := -I../src
HDR     := $(wildcard ../src/*.h)
SRC     := fb_host.c ../src/fb_ui.c ../src/fb_video.c ../src/fb_text.c \
           ../src/fb_gen.c ../src/fb_fmt.c ../src/fb_measures.c
OUT     := fb_host

all: $(OUT)

$(OUT): $(SRC) $(HDR)
	$(CC) $(CSTD) $(WARN) $(INC) $(SRC) -lm -o $(OUT)

run: $(OUT)
	./$(OUT) --frames 40 --dump shot.ppm

clean:
	rm -f $(OUT) *.ppm

.PHONY: all run clean
