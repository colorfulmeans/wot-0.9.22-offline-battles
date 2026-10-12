// Complete current Geometry.chunk preparation and one atomic Store::chunk.
// Original rows are owned temporarily during this synchronous call. The native
// Store receives only numbers; no Python object is retained between calls.
namespace destructible_prepare_law {
namespace d = offline_destructible;
namespace b = destructible_bridge;

bool unicode_space(unsigned c) {
    // CPython 2.7's Unicode 5.2 whitespace law; byte strip remains separate.
    return (c >= 9 && c <= 13) || (c >= 28 && c <= 32) || c == 0x85 ||
        c == 0xa0 || c == 0x1680 || c == 0x180e ||
        (c >= 0x2000 && c <= 0x200a) || c == 0x2028 || c == 0x2029 ||
        c == 0x202f || c == 0x205f || c == 0x3000;
}

bool named(PyObject *raw) {
    if (raw == none_object) return false;
    if (raw && raw->ob_type == unicode_type) {
#ifdef WOT_HOST_PYTHON
        const auto *text = PyUnicode_AS_UNICODE(raw);
        const Py_ssize_t length = PyUnicode_GET_SIZE(raw);
#else
        const auto *text = read<const uint16_t *>(reinterpret_cast<const char *>(raw) + 12);
        const Py_ssize_t length = size(raw);
#endif
        for (Py_ssize_t i = 0; i < length; ++i)
            if (!unicode_space(static_cast<unsigned>(text[i]))) return true;
        return false;
    }
    // Normalization only supplies its truth value. Replacing slashes and
    // lowercasing cannot change emptiness; bytes.strip uses ASCII spaces.
    // Subclasses retain the original Python normalization path.
    if (!raw || raw->ob_type != field_keys[0]->ob_type) throw Unsupported();
#ifdef WOT_HOST_PYTHON
    // Host builds use the header-owned accessor on either CI architecture.
    // Keep the game-layout assertion when that host is also 32-bit.
    static_assert(sizeof(void *) != 4 || offsetof(PyStringObject, ob_sval) == 20,
                  "The 32-bit host must match the CPython string layout");
    const char *text = PyString_AS_STRING(raw);
#else
    const char *text = reinterpret_cast<const char *>(raw) + 20;
#endif
    for (Py_ssize_t i = 0; i < size(raw); ++i) {
        const unsigned char c = static_cast<unsigned char>(text[i]);
        if (c != ' ' && c != '\t' && c != '\n' && c != '\r' &&
            c != '\v' && c != '\f') return true;
    }
    return false;
}

struct Kind { bool missing; int value; };
Kind kind(PyObject *raw) {
    return raw == none_object ? Kind{true, 0} : Kind{false, index_value(raw)};
}
bool equal(Kind a, Kind c) {
    return a.missing == c.missing && (a.missing || a.value == c.value);
}

bool boxes_present(PyObject *raw) {
    if (raw == none_object) return false;
    require_sequence(raw, 0);
    return size(raw) != 0;
}

struct Prepared {
    d::Chunk chunk;
    std::map<int, PyObject *> originals;
    std::vector<int> insertion_order;
    Prepared() = default;
    Prepared(const Prepared &) = delete;
    Prepared &operator=(const Prepared &) = delete;
    Prepared(Prepared &&other) noexcept
        : chunk(std::move(other.chunk)), originals(std::move(other.originals)),
          insertion_order(std::move(other.insertion_order)) {
        other.originals.clear();
    }
    ~Prepared() {
        for (const auto &entry : originals) decref(entry.second);
    }
};

void read_bins(PyObject *raw, std::map<d::Cell, std::vector<int>> &bins,
               Prepared &prepared) {
    require_sequence(raw, 0);
    for (Py_ssize_t i = 0; i < size(raw); ++i) {
        PyObject *pair = items(raw)[i];
        require_sequence(pair, 2, true);
        const auto cell = b::cell(items(pair)[0]);
        PyObject *source = items(pair)[1];
        require_sequence(source, 0);
        std::vector<int> indices;
        indices.reserve(static_cast<size_t>(size(source)));
        for (Py_ssize_t j = 0; j < size(source); ++j) {
            PyObject *item = items(source)[j];
            require_sequence(item, 10, true);
            const int index = index_value(items(item)[0]);
            auto prior = prepared.originals.find(index);
            if (prior == prepared.originals.end()) {
                prepared.originals.emplace(index, item);
                // Pin before result allocation can trigger Python collection.
                // Every exit releases this temporary reference through RAII.
                ++item->ob_refcnt;
                prepared.insertion_order.push_back(index);
            } else if (prior->second != item) {
                // The original compares all fields, possibly invoking custom
                // equality. Reject read-only and let that law decide.
                throw Unsupported();
            }
            indices.push_back(index);
        }
        if (!bins.emplace(cell, std::move(indices)).second) throw Unsupported();
    }
}

Prepared prepare(PyObject *origins, PyObject *extended, PyObject *types) {
    require_sequence(types, 4, true);
    Kind kinds[4];
    for (int i = 0; i < 4; ++i) kinds[i] = kind(items(types)[i]);
    Prepared result;
    read_bins(origins, result.chunk.origins, result);
    read_bins(extended, result.chunk.extended, result);
    for (const auto &entry : result.originals) {
        PyObject **row = items(entry.second);
        d::Item item;
        item.index = entry.first;
        item.position = {{finite_number(row[1]), finite_number(row[2]),
                          finite_number(row[3])}};
        const Kind type = kind(row[4]);
        item.tree = equal(type, kinds[0]);
        item.named = named(row[5]);
        item.catalog = boxes_present(row[8]) &&
            (equal(type, kinds[1]) || equal(type, kinds[2]) || equal(type, kinds[3]));
        item.radius = finite_number(row[9]);
        result.chunk.items.emplace(item.index, item);
    }
    return result;
}

PyObject *mapping_rows(const Prepared &value) {
    OwnedTuple out(value.insertion_order.size());
    for (size_t i = 0; i < value.insertion_order.size(); ++i) {
        const int index = value.insertion_order[i];
        OwnedTuple row(2);
        row.set(0, int_new(index));
        PyObject *original = value.originals.at(index);
        ++original->ob_refcnt;
        row.set(1, original);
        out.set(i, row.release());
    }
    return out.release();
}

template<class Profile>
PyObject *run(d::Store *store, PyObject *payload, Profile &profile) {
    require_sequence(payload, 4, true);
    PyObject **p = items(payload);
    const auto chunk_id = b::wide(p[0]);
    auto prepared = prepare(p[1], p[2], p[3]);
    // Allocate every Python result before committing. Unsupported input or
    // result allocation failure cannot partly replace the native chunk.
    PyObject *result = mapping_rows(prepared);
    try {
        profile.run(&d::Store::chunk, store, chunk_id, std::move(prepared.chunk));
    } catch (...) {
        decref(result);
        throw;
    }
    return result;
}
} // namespace destructible_prepare_law
