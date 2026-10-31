"""Local OpenGL 3.3 rendering with resident geometry and exact object layers.

A tiled GPU atlas stores the nearest fragment of each physical object. The
compositor sorts these layers per pixel, retaining the CPU renderer's alpha
and picking contract without CPU triangle rasterization or depth sorting.
"""
import math
import struct
import time

import numpy as np
from PIL import Image


_VERTEX = '''#version 330
uniform mat4 camera;
uniform mat3 rotation;
in vec3 position;
in vec3 normal;
in vec3 color;
in float identity;
out vec3 rgb;
out vec3 n;
flat out uint pick;
void main() {
    gl_Position = camera * vec4(position, 1.0);
    rgb = color; n = rotation * normal; pick = uint(identity + 0.5);
}
'''
_FRAGMENT = '''#version 330
uniform float opacity;
uniform float tint;
uniform uint selected;
uniform bool whole_selected;
uniform bool lighting;
in vec3 rgb;
in vec3 n;
flat in uint pick;
layout(location=0) out vec4 paint;
layout(location=1) out uint object_id;
void main() {
    float light = 0.0;
    if (lighting && length(n) > 0.001) {
        vec3 nn = normalize(n) * (n.z < 0.0 ? -1.0 : 1.0);
        light = -0.10 + 0.22 * clamp(dot(nn, vec3(-0.4,0.7,0.6)),0.0,1.0);
    }
    float amount = (whole_selected || (selected != 0u && selected == pick)) ? 0.25 : tint;
    vec3 c = amount >= 0.0 ? mix(rgb,vec3(1.0),amount) : rgb*(1.0+amount);
    c = light >= 0.0 ? mix(c,vec3(1.0),light) : c*(1.0+light);
    paint=vec4(c,opacity); object_id=pick;
}
'''
_QUAD = '''#version 330
void main() {
    vec2 p=vec2((gl_VertexID << 1) & 2, gl_VertexID & 2);
    gl_Position=vec4(p*2.0-1.0,0.0,1.0);
}
'''
_COMPOSITE = '''#version 330
uniform sampler2D colors;
uniform sampler2D depths;
uniform usampler2D identities;
uniform int count;
uniform int columns;
uniform ivec2 size;
layout(location=0) out vec4 result;
layout(location=1) out uint result_id;
void main() {
    float z[64]; vec4 rgba[64]; uint ids[64]; int used=0;
    for(int i=0;i<count;i++) {
        ivec2 p=ivec2(gl_FragCoord.xy)+ivec2(i%columns,i/columns)*size;
        float d=texelFetch(depths,p,0).r;
        vec4 c=texelFetch(colors,p,0);
        if(d>=1.0 || c.a<=0.0) continue;
        uint id=texelFetch(identities,p,0).r;
        int j=used;
        while(j>0 && z[j-1]<d) {
            z[j]=z[j-1]; rgba[j]=rgba[j-1]; ids[j]=ids[j-1]; j--;
        }
        z[j]=d; rgba[j]=c; ids[j]=id; used++;
    }
    vec3 out_rgb=vec3(23.0,27.0,34.0)/255.0; uint picked=0u;
    for(int i=0;i<used;i++) {
        out_rgb=mix(out_rgb,rgba[i].rgb,rgba[i].a);
        if(ids[i]!=0u && rgba[i].a>=0.08) picked=ids[i];
        if(ids[i]==0u && rgba[i].a>=0.999) picked=0u;
    }
    result=vec4(out_rgb,1.0); result_id=picked;
}
'''


class GpuRenderer:
    def __init__(self):
        import moderngl
        self.gl = moderngl
        self.ctx = moderngl.create_context(standalone=True, require=330)
        self.info = {k:self.ctx.info.get(k,'') for k in ('GL_VENDOR','GL_RENDERER','GL_VERSION')}
        self.meshes = []
        self._targets = []
        self._size = None
        self.uploads = 0
        self.frames = []
        with self.ctx:
            self.program = self.ctx.program(vertex_shader=_VERTEX, fragment_shader=_FRAGMENT)
            self.composite = self.ctx.program(vertex_shader=_QUAD, fragment_shader=_COMPOSITE)
            self.quad = self.ctx.vertex_array(self.composite, [])

    def load(self, objects):
        """Upload once per scene/material change, never on camera motion."""
        if len(objects)>64:
            raise ValueError('The viewer exceeded its 64 physical-object layers')
        with self.ctx:
            for vao, buffer in self.meshes:
                vao.release(); buffer.release()
            self.meshes=[]
            for obj in objects:
                rows=[]
                for triangle, color, pick in obj['triangles']:
                    p=np.asarray(triangle,dtype=np.float32)
                    normal=np.cross(p[1]-p[0],p[2]-p[0])
                    length=float(np.linalg.norm(normal))
                    if length: normal/=length
                    rows.extend(tuple(point)+tuple(normal)+tuple(c/255. for c in color)+(pick,)
                                for point in p)
                data=np.asarray(rows,dtype=np.float32).tobytes()
                buffer=self.ctx.buffer(data or b'\0'*40)
                vao=self.ctx.vertex_array(self.program,[(buffer,'3f 3f 3f 1f','position','normal','color','identity')])
                self.meshes.append((vao,buffer))
            self.uploads+=1

    def _resize(self,width,height,count):
        columns=max(1,math.ceil(math.sqrt(max(1,count))))
        rows=max(1,math.ceil(count/columns))
        key=(width,height,columns,rows)
        if key==self._size: return
        for resource in self._targets: resource.release()
        self._targets=[]
        atlas_size=(width*columns,height*rows)
        if max(atlas_size)>self.ctx.info['GL_MAX_TEXTURE_SIZE']:
            raise ValueError('The viewer atlas exceeds the graphics texture limit')
        self.color=self.ctx.texture(atlas_size,4,dtype='f2')
        self.ids=self.ctx.texture(atlas_size,1,dtype='u4')
        self.depth=self.ctx.depth_texture(atlas_size)
        self.depth.compare_func=''
        self.atlas=self.ctx.framebuffer((self.color,self.ids),self.depth)
        self.output=self.ctx.texture((width,height),4,dtype='f1')
        self.picks=self.ctx.texture((width,height),1,dtype='u4')
        self.frame=self.ctx.framebuffer((self.output,self.picks))
        self._targets=[self.atlas,self.frame,self.color,self.ids,self.depth,self.output,self.picks]
        self._size=key

    def render(self,width,height,camera,rotation,styles,selected=0,lighting=True):
        start=time.perf_counter()
        with self.ctx:
            self._resize(width,height,len(styles))
            columns=self._size[2]
            self.atlas.use();self.atlas.clear(0,0,0,0,depth=1.)
            self.ctx.enable_only(self.gl.DEPTH_TEST)
            self.program['camera'].write(np.asarray(camera,np.float32).T.tobytes())
            self.program['rotation'].write(np.asarray(rotation,np.float32).T.tobytes())
            self.program['selected'].value=int(selected)
            self.program['lighting'].value=lighting
            for index, ((vao,_), style) in enumerate(zip(self.meshes,styles)):
                if style['alpha']<=0: continue
                self.ctx.viewport=(index%columns*width,index//columns*height,width,height)
                self.program['opacity'].value=style['alpha']
                self.program['tint'].value=style.get('tint',0.)
                self.program['whole_selected'].value=style.get('selected',False)
                vao.render(self.gl.TRIANGLES)
            self.frame.use();self.ctx.viewport=(0,0,width,height)
            self.ctx.enable_only(self.gl.NOTHING)
            for unit,texture in enumerate((self.color,self.depth,self.ids)): texture.use(unit)
            for name,value in dict(colors=0,depths=1,identities=2,count=len(styles),columns=columns,size=(width,height)).items():
                self.composite[name].value=value
            self.quad.render(self.gl.TRIANGLES,vertices=3)
            raw=self.frame.read(components=3,alignment=1)
        image=Image.frombytes('RGB',(width,height),raw).transpose(Image.Transpose.FLIP_TOP_BOTTOM)
        self.frames.append((time.perf_counter()-start)*1000)
        self.frames=self.frames[-240:]
        return image

    def pick(self,x,y):
        width,height=self._size[:2]
        if not (0<=x<width and 0<=y<height): return 0
        with self.ctx:
            raw=self.frame.read(viewport=(int(x),height-1-int(y),1,1),components=1,attachment=1,dtype='u4')
        return struct.unpack('<I',raw)[0]

    def release(self):
        with self.ctx:
            for vao,buffer in self.meshes: vao.release();buffer.release()
            for resource in self._targets: resource.release()
            self.quad.release();self.program.release();self.composite.release()
        self.ctx.release()
