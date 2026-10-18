// Exercise the shipping search implementation; no engine collision acceptance.
#include "offline_navigation.h"
#include <algorithm>
#include <chrono>
#include <cmath>
#include <fstream>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <thread>
#include <vector>

int main(int argc, char **argv) {
    if (argc != 2) return 2;
    std::ifstream input(argv[1]);
    offline_navigation::MapInput map;
    input >> map.width >> map.height >> map.origin_x >> map.origin_z
          >> map.cell_size >> map.max_grade;
    map.has_bounds = true;
    for (auto &v : map.bounds) input >> v;
    for (int i=0; i<map.width*map.height; ++i) {
        double h; unsigned link, hazard;
        input >> h >> link >> hazard;
        map.heights.push_back(h == -999999 ? std::numeric_limits<double>::quiet_NaN() : h);
        map.links.push_back(link); map.hazards.push_back(hazard);
    }
    int count; input >> count;
    std::vector<offline_navigation::SearchInput> cases(count);
    for (int i=0; i<count; ++i) {
        auto &s=cases[i];
        input >> s.start[0] >> s.start[2] >> s.goal[0] >> s.goal[2];
        s.start[1]=s.goal[1]=1.1;
        s.max_expansions=4096; s.prefer_clearance=true;
        s.has_route_corridor=true; s.route_start=s.start; s.route_end=s.goal;
    }
    if (!input) throw std::runtime_error("incomplete benchmark input");
    const auto context=offline_navigation::open(std::move(map));
    std::vector<double> times;
    unsigned expanded=0, partial=0;
    const auto started=std::chrono::steady_clock::now();
    int submitted=0, completed=0;
    while (completed < count*3) {
        while (submitted < count*3 && submitted-completed < 29) {
            auto s=cases[submitted%count]; s.job_id=++submitted;
            if (!offline_navigation::submit(context, s)) throw std::runtime_error("submit failed");
        }
        auto result=offline_navigation::poll(context);
        if (!result.queries.empty()) throw std::runtime_error("unexpected engine query");
        for (const auto &c:result.completed) {
            if (c.status != 0) throw std::runtime_error("search failed");
            const auto &goal=cases[(c.job_id-1)%count].goal;
            if (c.path.empty() || std::hypot(c.path.back()[0]-goal[0],c.path.back()[2]-goal[2])>8.) ++partial;
            times.push_back(c.worker_seconds*1000); expanded+=c.expanded; ++completed;
        }
        if (std::chrono::duration<double>(std::chrono::steady_clock::now()-started).count()>90.)
            throw std::runtime_error("search timeout");
        std::this_thread::yield();
    }
    offline_navigation::close(context);
    std::sort(times.begin(), times.end());
    std::cout << "{\"jobs\":" << completed << ",\"partial_or_empty\":" << partial
              << ",\"expanded\":" << expanded << ",\"worker_p50_ms\":" << times[times.size()/2]
              << ",\"worker_p95_ms\":" << times[times.size()*95/100]
              << ",\"worker_max_ms\":" << times.back() << "}\n";
}
