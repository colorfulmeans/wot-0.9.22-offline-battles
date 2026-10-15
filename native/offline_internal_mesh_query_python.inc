// Current internal_mesh ray/nearest-surface walks. Borrow only visited builtin
// nodes under the GIL. No tree rebuild, geometry approximation or retained state.
namespace internal_mesh_query_law {
using Point = std::array<double, 3>;
Point sub(const Point &a, const Point &b) {
    return {{a[0]-b[0], a[1]-b[1], a[2]-b[2]}};
}
double dot(const Point &a, const Point &b) {
    return a[0]*b[0] + a[1]*b[1] + a[2]*b[2];
}
Point cross(const Point &a, const Point &b) {
    return {{a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2],
             a[0]*b[1]-a[1]*b[0]}};
}
Point add_scaled(const Point &a, const Point &b, double scale) {
    return {{a[0]+b[0]*scale, a[1]+b[1]*scale, a[2]+b[2]*scale}};
}
Point point(PyObject *raw, bool vertex=false) {
    require_sequence(raw, 3, true);
    Point out = {};
    for (int i=0; i<3; ++i) {
        // prepare() produces float vertices. Unprepared integer-only meshes
        // can use arbitrary-precision arithmetic and keep the Python oracle.
        if (vertex && items(raw)[i]->ob_type != float_type) throw Unsupported();
        out[i] = finite_number(items(raw)[i]);
        if (std::abs(out[i]) > 1.e6) throw Unsupported();
    }
    return out;
}
Py_ssize_t index(PyObject *raw, Py_ssize_t count) {
    const auto value = identity(raw);
    if (value < 0 || value >= count) throw Unsupported();
    return static_cast<Py_ssize_t>(value);
}
struct Triangle { Point a,b,c; std::array<Py_ssize_t,3> indices; };
struct Mesh {
    PyObject *vertices, *faces, *root;
    explicit Mesh(PyObject *raw, Py_ssize_t width=3) {
        require_sequence(raw, width, true);
        vertices=items(raw)[0]; faces=items(raw)[1]; root=items(raw)[2];
        require_sequence(vertices, 0); require_sequence(faces, 0);
    }
    size_t node_limit() const { return 2*static_cast<size_t>(size(faces))+1; }
    Triangle triangle(Py_ssize_t face_index) const {
        PyObject *face=items(faces)[face_index]; require_sequence(face,3,true);
        Triangle result;
        for (int i=0; i<3; ++i) result.indices[i]=index(items(face)[i],size(vertices));
        result.a=point(items(vertices)[result.indices[0]],true);
        result.b=point(items(vertices)[result.indices[1]],true);
        result.c=point(items(vertices)[result.indices[2]],true);
        return result;
    }
};
void count_triangle(long &count) {
    if (count==std::numeric_limits<long>::max()) throw Unsupported();
    ++count;
}
bool line_box(const Point &start,const Point &delta,const Point &low,
              const Point &high,double first,double last,double epsilon) {
    for (int a=0; a<3; ++a) {
        if (std::abs(delta[a]) < 1.e-15) {
            if (start[a] < low[a]-epsilon || start[a] > high[a]+epsilon) return false;
            continue;
        }
        double x=(low[a]-start[a])/delta[a], y=(high[a]-start[a])/delta[a];
        if (x>y) std::swap(x,y);
        first=std::max(first,x); last=std::min(last,y);
        if (first > last+epsilon) return false;
    }
    return true;
}
struct Hit { double t; int sign; };
bool triangle_line(const Point &start,const Point &delta,const Triangle &f,
                   double epsilon,Hit &hit) {
    const Point e1=sub(f.b,f.a), e2=sub(f.c,f.a), p=cross(delta,e2);
    const double det=dot(e1,p);
    if (std::abs(det)<=1.e-14) return false;
    const Point t=sub(start,f.a);
    const double u=dot(t,p)/det;
    if (u < -epsilon || u > 1.+epsilon) return false;
    const Point q=cross(t,e1);
    const double v=dot(delta,q)/det;
    if (v < -epsilon || u+v > 1.+epsilon) return false;
    hit={dot(e2,q)/det, det>0.?1:-1};
    if (!std::isfinite(hit.t)) throw Unsupported();
    return true;
}
struct Group { double t; int mask; };
struct LineResult { std::vector<Group> groups; long tested=0; };
LineResult line_hits(const Mesh &mesh,PyObject *orientations,const Point &start,
                     const Point &delta,double first,double last,double epsilon) {
    std::vector<PyObject *> stack(1,mesh.root);
    std::vector<Hit> hits;
    LineResult result; size_t visited=0;
    while (!stack.empty()) {
        if (++visited>mesh.node_limit()) throw Unsupported();
        PyObject *node=stack.back(); stack.pop_back(); require_sequence(node,5,true);
        PyObject **fields=items(node);
        if (!line_box(start,delta,point(fields[0]),point(fields[1]),first,last,epsilon))
            continue;
        if (fields[2]!=none_object) {
            stack.push_back(fields[2]); stack.push_back(fields[3]);
            continue; // Original Python stack.extend is right-first.
        }
        PyObject *indices=fields[4]; require_sequence(indices,0);
        for (Py_ssize_t j=0; j<size(indices); ++j) {
            count_triangle(result.tested);
            const auto face_index=index(items(indices)[j],size(mesh.faces));
            const auto triangle=mesh.triangle(face_index);
            Hit hit;
            if (triangle_line(start,delta,triangle,epsilon,hit) &&
                    first-epsilon<=hit.t && hit.t<=last+epsilon) {
                if (orientations!=none_object) {
                    require_sequence(orientations,face_index+1);
                    const auto sign=identity(items(orientations)[face_index]);
                    if (sign!=-1 && sign!=1) throw Unsupported();
                    hit.sign *= static_cast<int>(sign);
                }
                hits.push_back(hit);
            }
        }
    }
    // Preserve tuple ordering, stable ties and the first signed-zero timestamp.
    std::stable_sort(hits.begin(),hits.end(),[](const Hit &a,const Hit &b) {
        if (a.t!=b.t) return a.t<b.t;
        return a.sign<b.sign;
    });
    for (const auto &hit:hits) {
        const int mask=hit.sign<0?1:2;
        if (!result.groups.empty() && std::abs(hit.t-result.groups.back().t)<=1.e-9)
            result.groups.back().mask |= mask;
        else result.groups.push_back({hit.t,mask});
    }
    return result;
}
double divide(double a,double b) {
    if (b==0.) throw Unsupported(); // Python owns its original exception/counters.
    return a/b;
}
struct Closest { Point value; int corner; };
Closest triangle_closest(const Point &p,const Triangle &f) {
    const Point ab=sub(f.b,f.a), ac=sub(f.c,f.a), ap=sub(p,f.a);
    const double d1=dot(ab,ap), d2=dot(ac,ap);
    if (d1<=0. && d2<=0.) return {f.a,0};
    const Point bp=sub(p,f.b);
    const double d3=dot(ab,bp), d4=dot(ac,bp);
    if (d3>=0. && d4<=d3) return {f.b,1};
    const double vc=d1*d4-d3*d2;
    if (vc<=0. && d1>=0. && d3<=0.)
        return {add_scaled(f.a,ab,divide(d1,d1-d3)),-1};
    const Point cp=sub(p,f.c);
    const double d5=dot(ab,cp), d6=dot(ac,cp);
    if (d6>=0. && d5<=d6) return {f.c,2};
    const double vb=d5*d2-d1*d6;
    if (vb<=0. && d2>=0. && d6<=0.)
        return {add_scaled(f.a,ac,divide(d2,d2-d6)),-1};
    const double va=d3*d6-d5*d4;
    if (va<=0. && d4-d3>=0. && d5-d6>=0.)
        return {add_scaled(f.b,sub(f.c,f.b),divide(d4-d3,(d4-d3)+(d5-d6))),-1};
    const double denominator=divide(1.,va+vb+vc);
    return {add_scaled(add_scaled(f.a,ab,vb*denominator),ac,vc*denominator),-1};
}
double box_distance_sq(const Point &p,const Point &low,const Point &high) {
    double result=0.;
    for (int a=0; a<3; ++a) {
        const double value=std::max(std::max(low[a]-p[a],0.),p[a]-high[a]);
        result += std::pow(value,2.); // CPython 2.7 ordered sum and **2.
    }
    return result;
}
struct QueueNode { double bound; size_t serial; PyObject *node; };
struct Later {
    bool operator()(const QueueNode &a,const QueueNode &b) const {
        return a.bound!=b.bound ? a.bound>b.bound : a.serial>b.serial;
    }
};
struct DistanceResult {
    double squared=std::numeric_limits<double>::infinity();
    Point closest={}; Py_ssize_t vertex=-1; bool found=false; long tested=0;
};
DistanceResult nearest(const Mesh &mesh,const Point &p) {
    std::priority_queue<QueueNode,std::vector<QueueNode>,Later> queue;
    queue.push({0.,0,mesh.root}); size_t serial=0,visited=0;
    DistanceResult result;
    while (!queue.empty()) {
        const auto entry=queue.top(); queue.pop();
        if (entry.bound>result.squared) break;
        if (++visited>mesh.node_limit()) throw Unsupported();
        require_sequence(entry.node,5,true); PyObject **fields=items(entry.node);
        if (fields[2]!=none_object) {
            for (int i=2; i<=3; ++i) {
                PyObject *child=fields[i]; require_sequence(child,5,true);
                const double bound=box_distance_sq(p,point(items(child)[0]),point(items(child)[1]));
                if (bound<=result.squared) {
                    if (++serial>mesh.node_limit()) throw Unsupported();
                    queue.push({bound,serial,child});
                }
            }
            continue;
        }
        PyObject *indices=fields[4]; require_sequence(indices,0);
        for (Py_ssize_t i=0; i<size(indices); ++i) {
            count_triangle(result.tested);
            const auto triangle=mesh.triangle(index(items(indices)[i],size(mesh.faces)));
            const auto candidate=triangle_closest(p,triangle);
            const Point delta=sub(p,candidate.value);
            const double squared=dot(delta,delta);
            if (!std::isfinite(squared)) throw Unsupported();
            if (squared<result.squared) {
                result.squared=squared; result.closest=candidate.value; result.found=true;
                result.vertex=candidate.corner<0?-1:triangle.indices[candidate.corner];
            }
        }
    }
    return result;
}
template<class Profile>
PyObject *line_call(PyObject *geometry,PyObject *parameters,Profile &profile) {
    require_sequence(geometry,4,true); require_sequence(parameters,5,true);
    // Do not inspect orientations until an actual hit consumes them.
    const Mesh mesh(geometry,4);
    const Point start=point(items(parameters)[0]), delta=point(items(parameters)[1]);
    const double first=number(items(parameters)[2]), last=number(items(parameters)[3]);
    const double epsilon=finite_number(items(parameters)[4]);
    if (std::isnan(first) || std::isnan(last) || std::abs(epsilon)>1.e6) throw Unsupported();
    const auto result=profile.run([&] {
        return line_hits(mesh,items(geometry)[3],start,delta,first,last,epsilon);
    });
    OwnedTuple out(2),groups(result.groups.size());
    for (size_t i=0; i<result.groups.size(); ++i) {
        OwnedTuple row(2); row.set(0,float_new(result.groups[i].t));
        row.set(1,int_new(result.groups[i].mask)); groups.set(i,row.release());
    }
    out.set(0,groups.release()); out.set(1,int_new(result.tested)); return out.release();
}
template<class Profile>
PyObject *distance_call(PyObject *geometry,PyObject *parameters,Profile &profile) {
    const Mesh mesh(geometry); require_sequence(parameters,1,true);
    const Point p=point(items(parameters)[0]);
    const auto result=profile.run([&] {return nearest(mesh,p);});
    OwnedTuple out(4);
    out.set(0,float_new(std::sqrt(result.squared)));
    if (result.found) {
        OwnedTuple closest(3);
        for (int i=0; i<3; ++i) closest.set(i,float_new(result.closest[i]));
        out.set(1,closest.release());
    } else out.set(1,fallback());
    out.set(2,integer_result(result.vertex)); out.set(3,int_new(result.tested));
    return out.release();
}
} // namespace internal_mesh_query_law
