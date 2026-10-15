// Static parking selection only: preserve the Python directed graph law.
// No height/turn penalty, reverse-edge assumption, or live collision claim.
PyObject *WOT_CDECL parking_distances(PyObject *, PyObject *args) {
    NATIVE_PROFILE_ENTRY(parking_distances);
    try {
        require_sequence(args, 10, true);
        PyObject **row = items(args);
        const int width = index_value(row[0]), height = index_value(row[1]);
        const int64_t count64 = static_cast<int64_t>(width) * height;
        const double cell = finite_number(row[2]);
        if (width <= 0 || width > 4096 || height <= 0 || height > 4096 ||
            count64 <= 0 || count64 > 1000000 || cell <= 0. || cell > 32.) throw Unsupported();
        const int count = static_cast<int>(count64);
        require_sequence(row[3], 2, true); require_sequence(row[4], 4, true);
        const double ox = finite_number(items(row[3])[0]), oz = finite_number(items(row[3])[1]);
        double bounds[4];
        for (int i = 0; i < 4; ++i) bounds[i] = finite_number(items(row[4])[i]);
        require_sequence(row[5], 8, true);
        int dx[8], dz[8]; double lengths[8];
        for (int bit = 0; bit < 8; ++bit) {
            PyObject *edge = items(row[5])[bit]; require_sequence(edge, 2, true);
            dx[bit] = index_value(items(edge)[0]); dz[bit] = index_value(items(edge)[1]);
            if (std::abs(dx[bit]) > 1 || std::abs(dz[bit]) > 1 ||
                (dx[bit] == 0 && dz[bit] == 0)) throw Unsupported();
            for (int j = 0; j < bit; ++j)
                if (dx[j] == dx[bit] && dz[j] == dz[bit]) throw Unsupported();
            lengths[bit] = cell * std::hypot(dx[bit], dz[bit]);
        }
        for (int field = 6; field <= 8; ++field) require_sequence(row[field], count, true);
        std::vector<unsigned> links(count);
        std::vector<unsigned char> usable(count);
        for (int i = 0; i < count; ++i) {
            links[i] = static_cast<unsigned>(index_value(items(row[7])[i]));
            const int hazards = index_value(items(row[8])[i]);
            PyObject *value = items(row[6])[i];
            if (value == none_object || (hazards & 15)) continue;
            if (value->ob_type == bool_type) throw Unsupported();
            finite_number(value); // No arbitrary Python conversion callbacks.
            const double x = ox + (i % width) * cell, z = oz + (i / width) * cell;
            usable[i] = x >= bounds[0] && x <= bounds[2] && z >= bounds[1] && z <= bounds[3];
        }
        const int start = index_value(row[9]);
        if (start < 0 || start >= count || !usable[start]) throw Unsupported();
        auto distances = profile.run([&]() {
            std::vector<double> out(count, std::numeric_limits<double>::infinity());
            using Item = std::pair<double, int>;
            std::priority_queue<Item, std::vector<Item>, std::greater<Item>> todo;
            out[start] = 0.; todo.push({0., start});
            while (!todo.empty()) {
                const auto item = todo.top(); todo.pop();
                const double length = item.first; const int index = item.second;
                if (length != out[index]) continue;
                const int x = index % width, z = index / width;
                for (int bit = 0; bit < 8; ++bit) {
                    if (!(links[index] & (1u << bit))) continue;
                    const int nx = x + dx[bit], nz = z + dz[bit];
                    if (nx < 0 || nx >= width || nz < 0 || nz >= height) continue;
                    const int next = nz * width + nx;
                    if (!usable[next]) continue;
                    const double cost = length + lengths[bit];
                    if (cost < out[next]) { out[next] = cost; todo.push({cost, next}); }
                }
            }
            return out;
        });
        NativeProfilePhase packing(NativePhase::Pack);
        OwnedTuple result(count);
        for (int i = 0; i < count; ++i)
            result.set(i, std::isfinite(distances[i]) ? float_new(distances[i]) : fallback());
        return result.release();
    } catch (const PythonAllocationFailed &) { profile.fail(); return 0; }
      catch (...) { profile.fail(); return fallback(); }
}
