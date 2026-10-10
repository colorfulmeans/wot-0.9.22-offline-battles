// The release's reduced suspension solve only. Queries, history, motion
// acceptance and damage remain with the existing player/Bot adapters.
namespace release_suspension {
using State = std::array<double,6>;
struct Point {
    double x,y,z,k=0.,damping=0.,compression=0.,maximum=0.,force=0.,penetration=0.,ground=0.;
    int side=0; bool spring=false,rigid=false,has_ground=false;
};
using Rotation = std::array<double,4>;
Rotation rotation(const State &s) {return {{std::sin(s[2]),std::cos(s[2]),std::sin(s[4]),std::cos(s[4])}};}
double height(const State &s,const Point &p,const Rotation &r) {return s[0]+(r[1]*(r[2]*p.x+r[3]*p.y)-r[0]*p.z);}
std::array<double,2> gradients(const Point &p,const Rotation &r) {return {{-r[0]*(r[2]*p.x+r[3]*p.y)-r[1]*p.z,r[1]*(r[3]*p.x-r[2]*p.y)}};}
// CPython's finite fsum partials, including its final half-even correction.
double sum(const std::vector<double> &values) {
    std::vector<double> partials;
    for(double x:values) {
        std::size_t i=0;
        for(double y:partials) {
            if(std::abs(x)<std::abs(y))std::swap(x,y);
            const double hi=x+y,lo=y-(hi-x);
            if(lo!=0.)partials[i++]=lo;
            x=hi;
        }
        partials.resize(i);partials.push_back(x);
    }
    double hi=0.,lo=0.;std::size_t n=partials.size();
    if(n) {
        hi=partials[--n];
        while(n) {const double x=hi,y=partials[--n];hi=x+y;lo=y-(hi-x);if(lo!=0.)break;}
        if(n&&((lo<0.&&partials[n-1]<0.)||(lo>0.&&partials[n-1]>0.))) {
            const double y=lo*2.,x=hi+y;if(y==x-hi)hi=x;
        }
    }
    return hi;
}
bool stable(const State &s,const std::vector<Point> &points,const std::vector<bool> &contact) {
    using XZ=std::array<double,2>;const auto r=rotation(s);std::vector<XZ> samples;
    for(std::size_t i=0;i<points.size();++i)if(contact[i]) {
        const auto &p=points[i];samples.push_back({{r[3]*p.x-r[2]*p.y,r[0]*(r[2]*p.x+r[3]*p.y)+r[1]*p.z}});
    }
    std::sort(samples.begin(),samples.end());samples.erase(std::unique(samples.begin(),samples.end()),samples.end());
    if(samples.size()<3)return false;
    auto cross=[](const XZ &a,const XZ &b,const XZ &c){return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0]);};
    std::vector<XZ> lower,upper;
    auto push=[&](std::vector<XZ> &chain,const XZ &p){while(chain.size()>=2&&cross(chain[chain.size()-2],chain.back(),p)<=0.)chain.pop_back();chain.push_back(p);};
    for(const auto &p:samples)push(lower,p);
    for(auto it=samples.rbegin();it!=samples.rend();++it)push(upper,*it);
    lower.pop_back();upper.pop_back();lower.insert(lower.end(),upper.begin(),upper.end());
    if(lower.size()<3)return false;
    const XZ origin={{0.,0.}};
    for(std::size_t i=0;i<lower.size();++i)if(cross(lower[(i+lower.size()-1)%lower.size()],lower[i],origin)<=1.e-10)return false;
    return true;
}
struct Result {State state;int contacts=0,rigid=0,touched=0;bool left=false,right=false,impact=false;double impact_speed=0.,compression=0.,excess=0.;};
Result solve(const std::array<double,5> &params,State s,const std::vector<Point> &points,double dt,double support,const std::array<double,9> &tuning,int max_steps) {
    const double im=1./params[0],ip=1./params[1],ir=1./params[2];
    const double total=std::max(0.,std::min(.2,dt));
    const int steps=static_cast<int>(std::min(double(max_steps),std::max(1.,std::ceil(total/params[3]))));
    const double step=total/steps;const int iterations=static_cast<int>(params[4]);
    Result out;std::vector<bool> touched(points.size(),false),contact(points.size(),false);bool transition=false;
    double va=0.,pa=0.,ra=0.;
    auto impact=[&](double speed){if(!out.impact){out.impact_speed=speed;out.impact=true;}else out.impact_speed=std::min(out.impact_speed,speed);};
    for(int sub=0;sub<steps;++sub) {
        auto r=rotation(s);const double force_offset=-support*std::max(0.,total-step*sub),projection_offset=-support*std::max(0.,total-step*(sub+1));
        double force=-params[0]*tuning[0],pitch_torque=0.,roll_torque=0.;int contacts=0;
        const double initial_speed=s[1],relative_speed=initial_speed-support;
        for(std::size_t i=0;i<points.size();++i) {
            const auto &p=points[i];if(!p.has_ground)continue;
            const double gap=p.ground+force_offset-height(s,p,r),compression=p.compression+gap;
            if(p.spring?compression<=0.:gap< -tuning[1])continue;
            touched[i]=true;++contacts;if(!transition&&relative_speed<0.)impact(initial_speed);
            if(!p.spring)continue;
            out.compression=std::max(out.compression,compression);const auto g=gradients(p,r);
            const double velocity=(s[1]+g[0]*s[3]+g[1]*s[5])-support;
            double f=p.k*compression-p.damping*velocity;
            if(compression>p.maximum){const double excess=compression-p.maximum;f+=p.k*8.*excess*(1.+excess/std::max(p.maximum,.01));}
            f=std::max(0.,std::min(p.force,f));force+=f;pitch_torque+=g[0]*f;roll_torque+=g[1]*f;
        }
        if(contacts)transition=true;
        if(!contacts){const double decay=std::exp(-tuning[2]*step);s[3]=std::max(-tuning[3],std::min(tuning[3],s[3]))*decay;s[5]=std::max(-tuning[3],std::min(tuning[3],s[5]))*decay;}
        va=force/params[0];pa=pitch_torque/params[1];ra=roll_torque/params[2];
        s[1]+=va*step;s[3]+=pa*step;s[5]+=ra*step;s[0]+=s[1]*step;s[2]+=s[3]*step;s[4]+=s[5]*step;
        const double before_v=s[1],before_p=s[3],before_r=s[5];bool projected=false;
        struct Row {double excess,pg,rg,denom;};
        for(int iteration=0;iteration<iterations;++iteration) {
            r=rotation(s);std::vector<Row> rows;double maximum=0.;
            for(std::size_t i=0;i<points.size();++i) {
                const auto &p=points[i];if(!p.has_ground)continue;
                const double excess=p.ground+projection_offset-height(s,p,r)-p.penetration;if(excess<=1.e-5)continue;
                touched[i]=true;projected=true;const auto g=gradients(p,r);const double pg=-g[0],rg=-g[1],denom=im+pg*pg*ip+rg*rg*ir;
                if(denom<=1.e-12)continue;
                rows.push_back({excess,pg,rg,denom});maximum=std::max(maximum,excess);
            }
            if(rows.empty())break;
            const double tolerance=std::max(1.e-10,maximum*1.e-8);std::array<std::vector<double>,6> changes;
            for(const auto &row:rows)if(maximum-row.excess<=tolerance) {
                const double velocity=(s[1]+ -row.pg*s[3]+ -row.rg*s[5])-support;
                const double impulse=velocity<0.? -velocity/row.denom:0.,position=row.excess/row.denom;
                changes[0].push_back(impulse*im);changes[1].push_back(-impulse*row.pg*ip);changes[2].push_back(-impulse*row.rg*ir);
                changes[3].push_back(position*im);changes[4].push_back(-position*row.pg*ip);changes[5].push_back(-position*row.rg*ir);
            }
            const double scale=1./changes[0].size();s[1]+=sum(changes[0])*scale;s[3]+=sum(changes[1])*scale;s[5]+=sum(changes[2])*scale;s[0]+=sum(changes[3])*scale;s[2]+=sum(changes[4])*scale;s[4]+=sum(changes[5])*scale;
        }
        r=rotation(s);double remaining=0.;
        for(std::size_t i=0;i<points.size();++i){const auto &p=points[i];if(!p.has_ground)continue;const double excess=p.ground+projection_offset-height(s,p,r)-p.penetration;if(excess>0.){remaining=std::max(remaining,excess);touched[i]=true;projected=true;}}
        if(remaining>0.)s[0]+=remaining+1.e-9;
        if(projected){if(step>0.){va+=(s[1]-before_v)/step;pa+=(s[3]-before_p)/step;ra+=(s[5]-before_r)/step;}if(!transition&&before_v-support<0.)impact(before_v);transition=true;}
    }
    const auto r=rotation(s);
    for(std::size_t i=0;i<points.size();++i) {
        const auto &p=points[i];if(!p.has_ground)continue;const double gap=p.ground-height(s,p,r);
        const bool active=p.spring?p.compression+gap>0.:gap>=-tuning[1];
        out.excess=std::max(out.excess,gap-p.penetration);
        if(active){contact[i]=touched[i]=true;++out.contacts;if(p.rigid)++out.rigid;if(p.side<0)out.left=true;else if(p.side>0)out.right=true;}
    }
    if(out.contacts&&!transition&&s[1]-support<0.)impact(s[1]);
    if(out.contacts&&total>0.&&stable(s,points,contact)) {
        if(std::abs(va)<tuning[4]&&std::abs(s[1]-support)<tuning[5])s[1]=support;
        if(std::abs(pa)<tuning[6]&&std::abs(s[3])<tuning[7])s[3]=0.;
        if(std::abs(ra)<tuning[6]&&std::abs(s[5])<tuning[7])s[5]=0.;
    }
    out.touched=static_cast<int>(std::count(touched.begin(),touched.end(),true));out.state=s;return out;
}
}

PyObject *WOT_CDECL release_suspension_step(PyObject *,PyObject *args) {
    NATIVE_PROFILE_ENTRY(release_suspension_step);
    try {
        namespace s=release_suspension;require_sequence(args,7,true);auto **a=items(args);
        std::array<double,5> params;world_array(a[0],params.data(),5);s::State state;world_array(a[3],state.data(),6);
        params[4]=index_value(items(a[0])[4]);
        require_sequence(a[4],2,true);std::array<double,9> tuning;world_array(a[6],tuning.data(),9);
        require_sequence(a[5],2,true);const double dt=finite_number(items(a[5])[0]),support=finite_number(items(a[5])[1]);
        const int max_steps=index_value(items(a[6])[8]);
        if(params[0]<=0.||params[1]<=0.||params[2]<=0.||params[3]<=0.||params[4]<0.||params[4]>256.||std::floor(params[4])!=params[4]||max_steps<1||max_steps>128)throw Unsupported();
        std::vector<s::Point> points;
        for(int family=0;family<2;++family){PyObject *rows=a[family+1],*ground=items(a[4])[family];require_sequence(rows,0);require_sequence(ground,size(rows),true);if(size(rows)>256)throw Unsupported();
            for(Py_ssize_t i=0;i<size(rows);++i){auto *raw=items(rows)[i];require_sequence(raw,family==0?9:6,true);double row[9]={};world_array(raw,row,family==0?9:6);s::Point p;p.x=row[0];p.y=row[1];p.z=row[2];p.spring=family==0;
                if(p.spring){p.k=row[3];p.damping=row[4];p.compression=row[5];p.maximum=row[6];p.force=row[7];p.side=index_value(items(raw)[8]);p.penetration=p.maximum-p.compression;}
                else{p.penetration=row[3];p.side=index_value(items(raw)[4]);p.rigid=row[5]!=0.;}
                PyObject *g=items(ground)[i];p.has_ground=!absent(g);if(p.has_ground)p.ground=finite_number(g);points.push_back(p);
            }
        }
        auto out=profile.run(s::solve,params,state,points,dt,support,tuning,max_steps);
        for(double value:out.state)if(!std::isfinite(value))throw Unsupported();
        OwnedTuple result(16);for(unsigned i=0;i<6;++i)result.set(i,float_new(out.state[i]));
        result.set(6,int_new(out.contacts));result.set(7,int_new(out.rigid));result.set(8,int_new(out.contacts==0));result.set(9,int_new(!out.left));result.set(10,int_new(!out.right));result.set(11,int_new(out.touched!=0));result.set(12,int_new(out.touched));result.set(13,out.impact?float_new(out.impact_speed):fallback());result.set(14,float_new(out.compression));result.set(15,float_new(out.excess));return result.release();
    }catch(const PythonAllocationFailed &){profile.fail();return 0;}catch(...){profile.fail();return fallback();}
}
