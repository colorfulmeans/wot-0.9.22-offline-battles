// Ordered world query batches share the audited main-thread capabilities.
// Effects stay on the Python authority; engine hits live only for this call.
struct NativeWorldQuery {
    PyObject *dispatcher;
    sim_motion_bridge::WorldFrontier *frontier;
    std::exception_ptr error;
    bool supplied_departing;
    engine_query::Object invoke(unsigned op,OwnedTuple &rows,size_t count) {
        OwnedTuple args(2);args.set(0,int_new(op));args.set(1,rows.release());
        WorldObject owned(args.release());
        return engine_query::Object(profiled_object_call(
            NativeCallback::World,"world",static_cast<int>(op),count,dispatcher,owned.get()));
    }
    int dispatch(unsigned op,const WorldRequest *requests,unsigned count,WorldResponse *responses) {
        NativeProfilePhase bridge(NativePhase::Pack);
        if(op==WORLD_DEPARTING) {
            if(count!=1)throw Unsupported();
            frontier->departure(requests[0]);return 1;
        }
        if(op==WORLD_HORIZONTAL || op==WORLD_GROUND) {
            bool stopped=false;
            for(unsigned i=0;i<count;++i) {
                auto &response=responses[i];const auto &request=requests[i];
                if(stopped || (request.flags&4)) {
                    std::memcpy(response.start,request.start,sizeof response.start);
                    std::memcpy(response.end,request.end,sizeof response.end);
                    stopped=stopped || (op==WORLD_GROUND && (request.flags&1));
                    continue;
                }
                engine_query::Object local;
                PyObject *filter=frontier->filter.get();
                if(!frontier->prepared) {
                    if(op!=WORLD_GROUND)throw Unsupported();
                    OwnedTuple rows(1);rows.set(0,world_request(WORLD_GROUND,request));
                    local=invoke(7,rows,1);filter=local.get();
                }
                std::function<bool(PyObject *)> departing;
                if(supplied_departing)departing=[&](PyObject *hit) {
                    OwnedTuple rows(1);engine_query::borrow(rows,0,hit);
                    return number(invoke(8,rows,1).get())!=0.;
                };
                frontier->ray(op,request,response,filter,departing);
                stopped=stopped || (op==WORLD_GROUND && !response.status && (request.flags&1));
            }
            return 1;
        }
        OwnedTuple rows(count);
        for(unsigned i=0;i<count;++i) {
            PyObject *value=world_request(op,requests[i]);
            if(op==WORLD_RESOLVE || op==WORLD_TRACE) {
                auto old=items(value)[2];auto hit=frontier->hit(requests[i].handle);
                ++hit->ob_refcnt;items(value)[2]=hit;decref(old);
            }
            rows.set(i,value);
        }
        auto result=invoke(op,rows,count);bridge.input();
        if(op==WORLD_FILTER) {
            frontier->filter=engine_query::Object::borrow(result.get());
            frontier->prepared=true;return 1;
        }
        if(op==WORLD_TRACE)return 1;
        if(op!=WORLD_RESOLVE)throw Unsupported();
        require_sequence(result.get(),count,true);
        for(unsigned i=0;i<count;++i) {
            responses[i].status=index_value(items(result.get())[i]);
            if(responses[i].status<0 || responses[i].status>2)throw Unsupported();
        }
        return 1;
    }
};
int native_world_query_dispatch(void *raw,unsigned op,const WorldRequest *requests,unsigned count,WorldResponse *responses) {
    auto &context=*static_cast<NativeWorldQuery *>(raw);
    try {return context.dispatch(op,requests,count,responses);}
    catch(...) {context.error=std::current_exception();return 0;}
}
PyObject *WOT_CDECL world_run_native(PyObject *,PyObject *args) {
    NATIVE_PROFILE_ENTRY(world_run_native);
    bool entered=false;
    try {
        require_sequence(args,4,true);double v[19];world_array(items(args)[0],v,19);
        WorldSnapshot snapshot={};std::memcpy(snapshot.position,v,3*sizeof(double));
        snapshot.yaw=v[3];snapshot.speed=v[4];snapshot.dt=v[5];snapshot.pitch=v[6];snapshot.roll=v[7];snapshot.motion_yaw=v[8];
        std::memcpy(snapshot.bounds,v+9,4*sizeof(double));std::memcpy(snapshot.heights,v+13,2*sizeof(double));
        snapshot.passive=v[15]!=0.;snapshot.airborne=v[16]!=0.;snapshot.exact_footprint=v[17]!=0.;snapshot.supplied_departing=v[18]!=0.;
        // Snapshot bounds must be rejected before any capability can run.
        if(snapshot.dt<0. || snapshot.bounds[0]>snapshot.bounds[1] || snapshot.bounds[2]<0. || snapshot.bounds[3]<0.)throw Unsupported();
        entered=true;
        sim_motion_bridge::WorldFrontier frontier(items(args)[2],items(args)[3],snapshot);
        NativeWorldQuery context={items(args)[1],&frontier,{},snapshot.supplied_departing!=0};
        const int result=profile.run(wot_world_run,&snapshot,native_world_query_dispatch,&context);
        if(context.error)std::rethrow_exception(context.error);
        return int_new(result);
    }catch(const PythonAllocationFailed &) {profile.fail();return 0;}
     catch(...) {profile.fail();return entered?int_new(-2):fallback();}
}
