# Camera speed relative to the car, per frame. A minimum above 0 means the camera never stops.
# Run: blender -b <out>/blocking.blend -P speed.py
import bpy
s=bpy.context.scene; c=bpy.data.objects["camera"]; car=bpy.data.objects["car"]; prev=None; out=[]
for f in range(1,s.frame_end+1):
    s.frame_set(f); rel=c.matrix_world.translation-car.matrix_world.translation
    if prev is not None: out.append((rel-prev).length*s.render.fps)
    prev=rel.copy()
print("RELSPEED min %.2f max %.2f m/s"%(min(out),max(out)))
print("RELSPEED every 24f:", " ".join("%.1f"%v for v in out[::24]))
