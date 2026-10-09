// Builtin dictionary construction and the exact-build assignment slot.
// Strict string-key templates and exact sequence rows never invoke user
// hashing/conversion. No borrowed Python object survives this synchronous call.
PyObject *WOT_CDECL control_pose(PyObject *,PyObject *args) {
    NATIVE_PROFILE_ENTRY(control_pose);
    try {
        require_sequence(args,1,true);PyObject *source=items(args)[0];
        if(!plain_dict(source))throw Unsupported();
        constexpr Field names[]={X,Y,Z,YAW,PITCH,ROLL,AIM_YAW,TURRET_YAW,GUN_PITCH,SPEED,VELOCITY};
        unsigned mask=1|2|4|8|(1<<9);
        double values[13]={};
        for(int i=0;i<10;++i){
            PyObject *value=field(source,names[i]);
            if(value)mask|=1u<<i;
            if(!absent(value)){
                values[i]=finite_number(value);
                if(values[i]==0.)values[i]=0.; // Match Python's "value or 0.0".
            }
        }
        PyObject *velocity=field(source,VELOCITY);
        if(velocity){
            mask|=1u<<10;require_sequence(velocity,3,true);
            for(int i=0;i<3;++i)values[10+i]=finite_number(items(velocity)[i]);
        }
        PyObject *position=field(source,POSITION);
        if(position&&position->ob_type==bool_type&&number(position)!=0.)throw Unsupported();
        const bool explicit_position=sequence(position)&&size(position)>0;
        if(explicit_position)require_sequence(position,3,true);
        else if(!absent(position)&&position->ob_type!=bool_type&&
                !(sequence(position)&&size(position)==0))throw Unsupported();
        OwnedTuple xyz(3),numbers(13),out(3);
        for(int i=0;i<3;++i){
            PyObject *value=explicit_position?items(position)[i]:field(source,names[i]);
            if(value){finite_number(value);engine_query::borrow(xyz,i,value);}
            else xyz.set(i,float_new(0.));
        }
        for(int i=0;i<13;++i)numbers.set(i,float_new(values[i]));
        out.set(0,xyz.release());out.set(1,numbers.release());out.set(2,int_new(mask));return out.release();
    }catch(const PythonAllocationFailed &){profile.fail();return 0;}
     catch(...){profile.fail();return fallback();}
}
PyObject *WOT_CDECL contact_materialize(PyObject *,PyObject *args) {
    NATIVE_PROFILE_ENTRY(contact_materialize);
    try {
        require_sequence(args,4,true);PyObject **a=items(args);
        require_sequence(a[0],0);require_sequence(a[1],size(a[0]),true);
        require_sequence(a[2],15,true);require_sequence(a[3],2,true);
        for(int i=0;i<15;++i)
            if(items(a[2])[i]->ob_type!=field_keys[ID]->ob_type)throw Unsupported();
        for(int i=0;i<2;++i)if(items(a[3])[i]->ob_type!=bool_type)throw Unsupported();
        size_t visible_count=0;
        for(Py_ssize_t i=0;i<size(a[0]);++i){
            PyObject *row=items(a[0])[i];require_sequence(row,5,true);
            if(!plain_dict(items(a[1])[i]))throw Unsupported();
            identity(field(items(a[1])[i],ID));
            const int flags=index_value(items(row)[1]);if(flags&1)++visible_count;
            if(items(row)[4]!=none_object){
                require_sequence(items(row)[4],3,true);PyObject **pose=items(items(row)[4]);
                require_sequence(pose[0],3,true);require_sequence(pose[1],13,true);
                const int mask=index_value(pose[2]);if(mask<0||mask>2047)throw Unsupported();
            }
        }
        if(!dict_set)throw Unsupported();
        return profile.run([&](){
            OwnedTuple targets(size(a[0])),visible(visible_count);size_t vi=0;
            for(Py_ssize_t i=0;i<size(a[0]);++i){
                PyObject **row=items(items(a[0])[i]);const int flags=index_value(row[1]);
                PyObject **pose=row[4]==none_object?nullptr:items(row[4]);
                const int mask=pose?index_value(pose[2]):0;
                OwnedTuple copy_args(1);engine_query::borrow(copy_args,0,items(a[1])[i]);
                WorldObject copy_args_owner(copy_args.release());
                PyObject *target=object_call(reinterpret_cast<PyObject *>(const_cast<void *>(dict_type)),copy_args_owner.get(),0);
                if(!target)throw PythonAllocationFailed();
                targets.set(i,target);
                if(!plain_dict(target))throw Unsupported();
                auto put=[&](int name,PyObject *value){
                    if(dict_set(target,items(a[2])[name],value)<0)throw PythonAllocationFailed();
                };
                for(int j=0;j<10;++j)if(mask&(1<<j))put(j,items(pose[1])[j]);
                if(mask&(1<<10)){
                    OwnedTuple velocity(3);
                    for(int j=0;j<3;++j)engine_query::borrow(velocity,j,items(pose[1])[10+j]);
                    WorldObject owned(velocity.release());put(10,owned.get());
                }
                if(pose)put(11,pose[0]);
                for(int j=0;j<3;++j)put(12+j,items(a[3])[(flags&(1<<j))?0:1]);
                if(flags&1){
                    OwnedTuple pair(2);engine_query::borrow(pair,0,field(target,ID));
                    engine_query::borrow(pair,1,target);visible.set(vi++,pair.release());
                }
            }
            OwnedTuple out(2);out.set(0,targets.release());out.set(1,visible.release());return out.release();
        });
    }catch(const PythonAllocationFailed &){profile.fail();return 0;}
     catch(...){profile.fail();return fallback();}
}
