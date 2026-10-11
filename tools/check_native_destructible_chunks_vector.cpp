// Test-only model of the reviewed float32 Math.Vector3 constructor and indexing.
// Loaded separately into a CPython host; never compiled into the shipping DLL.
#include <Python.h>
struct Vector { PyObject_HEAD float values[3]; };
int initialize(Vector *self, PyObject *args, PyObject *) {
    double x,y,z;
    if (!PyArg_ParseTuple(args,"ddd",&x,&y,&z)) return -1;
    self->values[0]=static_cast<float>(x);
    self->values[1]=static_cast<float>(y);
    self->values[2]=static_cast<float>(z);
    return 0;
}
PyObject *get(PyObject *raw, Py_ssize_t i) {
    if (i < 0 || i >= 3) {PyErr_SetString(PyExc_IndexError,"Vector3 index");return 0;}
    return PyFloat_FromDouble(reinterpret_cast<Vector *>(raw)->values[i]);
}
PySequenceMethods seq={};
PyTypeObject vector_type={PyVarObject_HEAD_INIT(0,0)};
PyMethodDef methods[]={{0,0,0,0}};
void install(PyObject *module) {
    seq.sq_item=get;
    vector_type.tp_name="Math.Vector3";
    vector_type.tp_basicsize=sizeof(Vector);
    vector_type.tp_flags=Py_TPFLAGS_DEFAULT;
    vector_type.tp_init=reinterpret_cast<initproc>(initialize);
    vector_type.tp_new=PyType_GenericNew;
    vector_type.tp_as_sequence=&seq;
    if (PyType_Ready(&vector_type)<0)return;
    Py_INCREF(&vector_type);
    PyModule_AddObject(module,"Vector3",reinterpret_cast<PyObject *>(&vector_type));
}
#if PY_MAJOR_VERSION >= 3
PyModuleDef module={PyModuleDef_HEAD_INIT,"native_chunk_vector",0,-1,methods};
PyMODINIT_FUNC PyInit_native_chunk_vector() {
    PyObject *result=PyModule_Create(&module);
    if(result)install(result);
    return result;
}
#else
PyMODINIT_FUNC initnative_chunk_vector() {install(Py_InitModule("native_chunk_vector",methods));}
#endif
