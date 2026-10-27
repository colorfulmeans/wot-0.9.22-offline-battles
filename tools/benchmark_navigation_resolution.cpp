// Exercise the shipping search implementation; no engine collision acceptance.
#include "offline_navigation.h"
#include <algorithm>
#include <chrono>
#include <cmath>
#include <fstream>
#include <iostream>
#include <iomanip>
#include <limits>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

int main(int argc, char **argv) {
    if (argc != 2 && argc != 3) return 2;
    const bool include_paths=argc==3 && std::string(argv[2])=="--paths";
    const bool complete=argc==3 && std::string(argv[2])=="--complete";
    if(include_paths)std::cout << std::setprecision(17);
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
    int patches;input >> patches;
    for(int n=0;n<patches;++n) {
        offline_navigation::LocalMeshInput p;
        input >> p.width >> p.height >> p.origin_x >> p.origin_z >> p.cell_size;
        for(int i=0;i<p.width*p.height;++i) {
            double h;unsigned l,v;input >> h >> l >> v;
            p.heights.push_back(h==-999999?std::numeric_limits<double>::quiet_NaN():h);
            p.links.push_back(l);p.hazards.push_back(v);
        }
        map.local_meshes.push_back(std::move(p));
    }
    int count; input >> count;
    unsigned complete_budget=map.width*map.height+1;
    for(const auto &p:map.local_meshes)complete_budget+=p.width*p.height;
    std::vector<offline_navigation::SearchInput> cases(count);
    for (int i=0; i<count; ++i) {
        auto &s=cases[i];
        input >> s.start[0] >> s.start[2] >> s.goal[0] >> s.goal[2];
        s.start[1]=s.goal[1]=1.1;
        s.max_expansions=complete ? complete_budget : 4096; s.prefer_clearance=true;
        s.has_route_corridor=true; s.route_start=s.start; s.route_end=s.goal;
    }
    if (!input) throw std::runtime_error("incomplete benchmark input");
    const auto context=offline_navigation::open(std::move(map));
    std::vector<double> times;
    std::vector<offline_navigation::Completion> incomplete;
    std::vector<offline_navigation::Completion> first_paths;
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
            if (c.path.empty() || std::hypot(c.path.back()[0]-goal[0],c.path.back()[2]-goal[2])>8.) {
                ++partial; incomplete.push_back(c);
            }
            times.push_back(c.worker_seconds*1000); expanded+=c.expanded; ++completed;
            if(include_paths && c.job_id<=static_cast<unsigned>(count))first_paths.push_back(c);
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
              << ",\"worker_max_ms\":" << times.back() << ",\"incomplete_cases\":[";
    for (size_t i=0;i<incomplete.size();++i) {
        const auto &c=incomplete[i];
        if(i) std::cout << ',';
        std::cout << "{\"case\":" << (c.job_id-1)%count << ",\"job\":" << c.job_id
                  << ",\"expanded\":" << c.expanded << ",\"has_end\":" << (!c.path.empty()?"true":"false");
        if(!c.path.empty()) std::cout << ",\"end\":[" << c.path.back()[0] << ',' << c.path.back()[1] << ',' << c.path.back()[2] << ']';
        std::cout << '}';
    }
    std::cout << ']';
    if(include_paths) {
        std::cout << ",\"paths\":[";
        for(size_t n=0;n<first_paths.size();++n) {
            const auto &c=first_paths[n];if(n)std::cout << ',';
            std::cout << "{\"case\":" << c.job_id-1 << ",\"expanded\":" << c.expanded << ",\"points\":[";
            for(size_t j=0;j<c.path.size();++j) {
                if(j)std::cout << ',';
                std::cout << '[' << c.path[j][0] << ',' << c.path[j][1] << ',' << c.path[j][2] << ']';
            }
            std::cout << "]}";
        }
        std::cout << ']';
    }
    std::cout << "}\n";
}
