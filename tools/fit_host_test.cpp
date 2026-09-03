/* fit_host_test.cpp -- record a whole FruitBench session on the desktop.
 *
 * Links the same fb_gen.c and fb_fit.cpp the watch runs, plus the SDK's FIT
 * encoder, and writes a real activity file. That is the only way to check the
 * part of this app that matters most -- 32 developer fields, 24 of them on the
 * record message and 8 on the lap message -- without a watch in hand, and
 * tools/fit_check.py then reads the result back and holds it against the
 * catalogue.
 *
 * Built and run by tools/host_test.sh.
 *
 *   ./fit_host_test out.fit [--seconds 900] [--seed 0x1234] [--lap 120]
 */

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <ctime>

#include "host_file.hpp"

#include "fb_fit.hpp"

extern "C" {
#include "fb_gen.h"
}

#ifndef APP_ID
#define APP_ID "0000000000000000"
#endif

int main(int argc, char **argv)
{
    const char *out = "fruitbench.fit";
    uint32_t seconds = 900u;
    uint32_t lap = 0u;                 /* 0: derive eight laps from the span */
    uint32_t seed = 0u;
    int i;

    for (i = 1; i < argc; ++i) {
        if (!std::strcmp(argv[i], "--seconds") && i + 1 < argc) {
            seconds = (uint32_t)std::strtoul(argv[++i], nullptr, 0);
        } else if (!std::strcmp(argv[i], "--lap") && i + 1 < argc) {
            lap = (uint32_t)std::strtoul(argv[++i], nullptr, 0);
        } else if (!std::strcmp(argv[i], "--seed") && i + 1 < argc) {
            seed = (uint32_t)std::strtoul(argv[++i], nullptr, 0);
        } else if (argv[i][0] != '-') {
            out = argv[i];
        } else {
            std::fprintf(stderr,
                         "usage: %s [out.fit] [--seconds N] [--seed S] "
                         "[--lap N]\n", argv[0]);
            return 2;
        }
    }

    if (lap == 0u) {
        lap = seconds >= 8u ? seconds / 8u : seconds;
    }
    if (seed == 0u) {
        seed = fb_gen_make_seed((uint32_t)std::time(nullptr), 0x5EEDu, 1u);
    }

    fb_gen_t gen;
    fb_gen_init(&gen, seed);

    /* Backdated like a fast recording on the watch, so the file ends now. */
    const std::time_t start = std::time(nullptr) - (std::time_t)seconds;

    HostFile file(out);
    if (!file.open(/*wMode=*/true, /*override=*/true)) {
        std::fprintf(stderr, "cannot create %s\n", out);
        return 1;
    }

    FbFitWriter writer(file);
    if (!writer.begin(start, APP_ID, seed)) {
        std::fprintf(stderr, "FIT header failed\n");
        return 1;
    }

    for (uint32_t t = 1u; t <= seconds; ++t) {
        fb_gen_step(&gen, t);
        if (!writer.addRecord(gen, start + (std::time_t)t)) {
            std::fprintf(stderr, "record %u failed\n", (unsigned)t);
            return 1;
        }
        if (t % lap == 0u && t != seconds) {
            /* Generator first: it draws the increment the lap message writes. */
            fb_gen_lap(&gen);
            if (!writer.addLap(gen, start + (std::time_t)t)) {
                std::fprintf(stderr, "lap at %u failed\n", (unsigned)t);
                return 1;
            }
        }
    }

    const bool ok = writer.finish(gen, start + (std::time_t)seconds);

    file.flush();
    const size_t bytes = file.size();
    file.close();

    std::printf("%s\n", out);
    std::printf("  seed        : %08X\n", seed);
    std::printf("  span        : %u s\n", (unsigned)seconds);
    std::printf("  records     : %u\n", (unsigned)writer.records());
    std::printf("  laps        : %u\n", (unsigned)writer.laps());
    std::printf("  bytes       : %zu (%.1f KB, %.1f B/record)\n", bytes,
                (double)bytes / 1024.0,
                writer.records() ? (double)bytes / writer.records() : 0.0);
    std::printf("  dev bytes   : %u on record, %u on lap, %u on session\n",
                (unsigned)FbFitWriter::recordDevBytes(),
                (unsigned)FbFitWriter::lapDevBytes(),
                (unsigned)FbFitWriter::sessionDevBytes());
    std::printf("  writer ok   : %s\n", (ok && writer.ok()) ? "yes" : "NO");

    return (ok && writer.ok()) ? 0 : 1;
}
