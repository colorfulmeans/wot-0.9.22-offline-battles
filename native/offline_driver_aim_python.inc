// Current-release aiming policy. No engine calls or retained Python state.
namespace driver_aim_law {
constexpr double pi=3.14159265358979323846;
double delta(double target,double current) {
    double value=target-current;
    while(value>pi)value-=pi*2.;
    while(value<-pi)value+=pi*2.;
    return value;
}
double clamp(double value,double low,double high) {
    return std::max(low,std::min(high,value));
}
std::array<double,3> aim(const double *v,int mode,bool has_target,bool engage,
                       bool movement,bool withdrawal,bool allow_rear) {
    // v: hull, target, minimum, maximum, turn, throttle, retained rear turn.
    if(!has_target || mode==1)return {{v[4],v[5],0.}};
    const bool limited=!(v[2]<=-pi+.1 && v[3]>=pi-.1);
    const double relative=delta(v[1],v[0]);
    const double margin=std::min(.04,std::max(0.,v[3]-v[2])*.25);
    if(limited && (v[6]!=0. || (allow_rear && std::abs(relative)>pi*.5)) &&
       !(v[2]+margin<=relative && relative<=v[3]-margin)) {
        const double center=(v[2]+v[3])*.5;
        double d=delta(v[1]-center,v[0]);
        if(v[6]!=0. && std::abs(relative)>pi*.5 && d*v[6]<0.)
            d+=std::copysign(2.*pi,v[6]);
        return {{clamp(d/.58,-1.,1.),0.,1.}};
    }
    if(mode==2) {
        const double center=(v[2]+v[3])*.5;
        if(withdrawal && v[5]<0. && std::abs(relative-center)<=.35 && limited) {
            if(v[2]+.02<=relative && relative<=v[3]-.02)return {{0.,v[5],0.}};
            return {{-clamp((relative-center)/.58,-.5,.5),v[5],1.}};
        }
        return {{v[4],v[5],0.}};
    }
    if((movement && !engage) || !limited)return {{v[4],v[5],0.}};
    if(v[2]+margin<=relative && relative<=v[3]-margin)
        return {{std::abs(v[5])<=.01?0.:v[4],v[5],0.}};
    return {{clamp(delta(v[1]-(v[2]+v[3])*.5,v[0])/.58,-1.,1.),0.,1.}};
}
PyObject *triple(const std::array<double,3> &v) {
    PyObject *out=tuple_new(3);if(!out)return 0;
    for(int i=0;i<3;++i) {
        items(out)[i]=float_new(v[i]);
        if(!items(out)[i]){decref(out);return 0;}
    }
    return out;
}
}
PyObject *WOT_CDECL driver_aim(PyObject *,PyObject *args) {
    NATIVE_PROFILE_ENTRY(driver_aim);
    try {
        require_sequence(args,3,true);auto a=items(args);
        const int op=index_value(a[0]);if(op<0 || op>3)throw Unsupported();
        const int count=op==0?7:op==1?4:op==2?7:2;
        require_sequence(a[1],count,true);double v[7]={};
        for(int i=0;i<count;++i) {
            v[i]=finite_number(items(a[1])[i]);
            // Bound normalization work; unusual inputs retain the reference law.
            if(std::abs(v[i])>100.*driver_aim_law::pi)throw Unsupported();
        }
        require_sequence(a[2],op==0?6:0,true);int flags[6]={};
        for(Py_ssize_t i=0;i<size(a[2]);++i)flags[i]=index_value(items(a[2])[i]);
        if(flags[0]<0 || flags[0]>2)throw Unsupported();
        for(int i=1;i<6;++i)if(flags[i]<0 || flags[i]>1)throw Unsupported();
        const auto result=profile.run([&] {
            using namespace driver_aim_law;
            if(op==0)return aim(v,flags[0],flags[1]!=0,flags[2]!=0,
                                flags[3]!=0,flags[4]!=0,flags[5]!=0);
            if(op==1)return std::array<double,3>{{
                (v[3]!=0. && std::abs(v[0])>pi*.5 && !(v[1]<=v[0] && v[0]<=v[2]))?
                    (v[3]>0.?v[2]:v[1]):clamp(v[0],v[1],v[2]),0.,0.}};
            if(op==2)return std::array<double,3>{{
                (std::abs(delta(v[0],v[1]+v[2]))<=v[5] &&
                 std::abs(v[3]-v[4])<=v[6])?1.:0.,0.,0.}};
            const double horizontal=std::cos(v[1]);
            return std::array<double,3>{{std::sin(v[0])*horizontal,-std::sin(v[1]),
                                         std::cos(v[0])*horizontal}};
        });
        if(op==1)return float_new(result[0]);
        if(op==2)return int_new(result[0]!=0.);
        return driver_aim_law::triple(result);
    }catch(const PythonAllocationFailed &){profile.fail();return 0;}
     catch(...){profile.fail();return fallback();}
}
