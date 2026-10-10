# Exact #1513 dictionary assignment boundary

The current Chinese HD 0.9.22.0.1 executable has the pinned PE identity already
checked by the bridge. Its PyDict_Type RVA is 0x01664d30. The x86 CPython 2.7
`tp_as_mapping` pointer (type offset 56) addresses RVA 0x01665c14; slot offset 8
addresses RVA 0x00be39c0. Disassembly shows a cdecl (dict, key, value) thunk:
NULL values call dictionary deletion; non-NULL values tail-call RVA 0x00be4980.
The new calls always supply non-NULL values and exact builtin string keys.

Initialization checks both pointers and all 35 thunk bytes. This is optional:
a mismatch disables the new dictionary materializer without disabling existing
native geometry. Host conformance uses PyDict_SetItem from actual x86 CPython
2.7.18. Reference identity, shallow metadata sharing, rejection paths and owned
references are tested; only the exact game can establish embedded acceptance.
