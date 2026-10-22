import sys, random, traceback, math
import os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import dieline_generator as g
seed=int(sys.argv[1]); N=int(sys.argv[2]); random.seed(seed)
fails=[]; built=0
for n in range(N):
    sid=random.choice(list(g.STYLE_BY_ID)); st=g.STYLE_BY_ID[sid]
    units=random.choice(("mm","in")); sp=g.default_spec(st,units)
    k=1/25.4 if units=="in" else 1
    sp.L=random.choice([20,60,150,300,900])*k*random.uniform(.6,1.6); sp.W=random.choice([20,60,100,250,700])*k*random.uniform(.6,1.6)
    sp.H=random.choice([10,40,80,200,500])*k*random.uniform(.6,1.6); sp.t=random.choice([0.3,1,2,3,5,8])*k
    if st.square: sp.W=sp.L
    sp.mode=random.choice(("inner","outer","manufacturer"))
    for key,_ in st.options:
        if random.random()<.35:
            sp.opts[key]=random.choice([0,1,2,3,5,10,40])*(1 if key in st.count_keys else k)*random.uniform(.5,1.5) if key not in st.count_keys else random.choice([0,1,2,3,5])
    for t in st.toggles:
        if random.random()<.4: sp.flags[t[0]]=True
    sp.folds=random.random()<.8
    try:
        r=g.generate(st,sp)
        if not r.ok or not r.drawing: continue
        built+=1
        look=r.look
        for f in g.EXPORT_REGISTRY:
            g.render_export(f.kind, r.drawing, units, ["n"], dict(g.GCODE_DEFAULTS), look)
        g.to_svg(r.drawing, units)
        if random.random()<.5:
            g.drawing_pdf(r, sp, g.drawing_defaults())
        if random.random()<.3 and hasattr(g,"model3d_bytes"): pass
    except Exception as e:
        fails.append((sid,units,sp.L,sp.W,sp.H,sp.t,sp.mode,dict(sp.opts),dict(sp.flags),repr(e)[:120],traceback.format_exc().splitlines()[-3:]))
print("specs",N,"built",built,"crashes",len(fails))
for f in fails[:5]: print(f)
