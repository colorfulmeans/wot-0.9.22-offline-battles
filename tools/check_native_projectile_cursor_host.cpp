// Isolated host harness for the production projectile include. This is not
// the embedded #1513 ABI or a replacement shipping extension.
#include <Python.h>
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <limits>
#include <vector>
#include "../native/offline_simulation_diagnostics.h"
#define WOT_CDECL
namespace {
struct Unsupported {};
struct PythonAllocationFailed {};
PyObject *none_object = Py_None;
long allocation_budget = -1;
bool allocation_allowed() {
    if (allocation_budget < 0) return true;
    if (allocation_budget == 0) { PyErr_NoMemory(); return false; }
    --allocation_budget;
    return true;
}
void decref(PyObject *o) { Py_XDECREF(o); }
PyObject *fallback() { Py_INCREF(Py_None); return Py_None; }
Py_ssize_t size(PyObject *o) { return Py_SIZE(o); }
bool sequence(PyObject *o) { return PyTuple_CheckExact(o) || PyList_CheckExact(o); }
PyObject **items(PyObject *o) {
    return PyTuple_CheckExact(o) ? reinterpret_cast<PyTupleObject *>(o)->ob_item :
                                  reinterpret_cast<PyListObject *>(o)->ob_item;
}
void require_sequence(PyObject *o, Py_ssize_t n, bool exact = false) {
    if (!sequence(o) || size(o) < n || (exact && size(o) != n)) throw Unsupported();
}
double finite_number(PyObject *o) {
    double v;
    if (PyFloat_CheckExact(o)) v = PyFloat_AS_DOUBLE(o);
    else if (PyBool_Check(o)) v = o == Py_True ? 1. : 0.;
#if PY_MAJOR_VERSION < 3
    else if (PyInt_CheckExact(o)) v = PyInt_AS_LONG(o);
#else
    else if (PyLong_CheckExact(o)) {
        int overflow = 0;
        const long value = PyLong_AsLongAndOverflow(o, &overflow);
        if (overflow || value < INT32_MIN || value > INT32_MAX) throw Unsupported();
        v = static_cast<double>(value);
    }
#endif
    else throw Unsupported();
    if (!std::isfinite(v)) throw Unsupported();
    return v;
}
int index_value(PyObject *o) {
#if PY_MAJOR_VERSION < 3
    if (!PyInt_CheckExact(o) && !PyBool_Check(o)) throw Unsupported();
#else
    if (!PyLong_CheckExact(o) && !PyBool_Check(o)) throw Unsupported();
#endif
    const double v = finite_number(o);
    if (v < INT32_MIN || v > INT32_MAX) throw Unsupported();
    return static_cast<int>(v);
}
int64_t identity(PyObject *o) { return static_cast<int64_t>(index_value(o)); }
PyObject *float_new(double v) { return allocation_allowed() ? PyFloat_FromDouble(v) : nullptr; }
PyObject *int_new(long v) {
    if (!allocation_allowed()) return nullptr;
#if PY_MAJOR_VERSION < 3
    return PyInt_FromLong(v);
#else
    return PyLong_FromLong(v);
#endif
}
PyObject *tuple_new(Py_ssize_t n) { return allocation_allowed() ? PyTuple_New(n) : nullptr; }
class OwnedTuple {
    PyObject *object_;
public:
    explicit OwnedTuple(size_t n): object_(tuple_new(static_cast<Py_ssize_t>(n))) {
        if (!object_) throw PythonAllocationFailed();
    }
    ~OwnedTuple() { decref(object_); }
    void set(size_t i, PyObject *v) {
        if (!v) throw PythonAllocationFailed();
        items(object_)[i] = v;
    }
    PyObject *release() { PyObject *v=object_; object_=0; return v; }
};
#include "../native/offline_projectile_math_python.inc"
PyObject *test_allocation_budget(PyObject *, PyObject *args) {
    long value;
    if (!PyArg_ParseTuple(args, "l", &value)) return nullptr;
    allocation_budget = value;
    Py_RETURN_NONE;
}
PyObject *test_diag_begin(PyObject *, PyObject *) {
    if (!offline_simulation::diagnostics::ledger().begin(1, 1)) {
        PyErr_SetString(PyExc_RuntimeError, "diagnostic begin failed"); return nullptr;
    }
    Py_RETURN_NONE;
}
PyObject *test_diag_end(PyObject *, PyObject *) {
    auto &ledger = offline_simulation::diagnostics::ledger();
    if (!ledger.end(1)) { PyErr_SetString(PyExc_RuntimeError, "diagnostic end failed"); return nullptr; }
    OwnedTuple result(ledger.entry_count);
    for (size_t i = 0; i < ledger.entry_count; ++i) {
        const auto &row = ledger.entries[ledger.entry_indices[i]];
        result.set(i, Py_BuildValue("(iKKddd)", row.opcode,
            static_cast<unsigned long long>(row.calls),
            static_cast<unsigned long long>(row.errors), row.parse, row.body, row.pack));
    }
    return result.release();
}
PyMethodDef methods[] = {
    {"test_allocation_budget", test_allocation_budget, METH_VARARGS, "Inject allocator failure."},
    {"test_diag_begin", test_diag_begin, METH_NOARGS, "Enable the production diagnostic scope."},
    {"test_diag_end", test_diag_end, METH_NOARGS, "Drain the production diagnostic scope."},
    {"projectile_math", projectile_math, METH_VARARGS, "Isolated projectile conformance."},
    {0, 0, 0, 0}
};
#if PY_MAJOR_VERSION >= 3
PyModuleDef module = {PyModuleDef_HEAD_INIT, "offline_math_batch_native", 0, -1, methods};
#endif
}
#if PY_MAJOR_VERSION >= 3
PyMODINIT_FUNC PyInit_offline_math_batch_native() { return PyModule_Create(&module); }
#else
PyMODINIT_FUNC initoffline_math_batch_native() { Py_InitModule("offline_math_batch_native", methods); }
#endif
