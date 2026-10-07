// Included by bend_viewer_test.cpp; exercises the actual GPU shader and buffers.
void bendPointChecks(const std::string& directory) {
    assert(BendPoints::selectedIndices({0,1,2,0,2})==std::vector<GLuint>({2,4}));
    std::vector<unsigned char> many(100000,2);
    auto indices=BendPoints::selectedIndices(many);
    assert(indices.size()==BendPoints::channelLimit && indices.front()==0 && indices.back()>99900);
    assert(std::adjacent_find(indices.begin(),indices.end())==indices.end());
    assert(BendPoints::selectedIndices({0,1,0}).empty());
    BendPoints points;
    // Capture the shader's output before projection; compare independently with
    // the existing centerline and a quaternion-rotated cross section and tails.
    const char* varying="vWorldPosition";
    glTransformFeedbackVaryings(points.program(),1,&varying,GL_INTERLEAVED_ATTRIBS);
    glLinkProgram(points.program());
    GLuint input,output;glGenBuffers(1,&input);glGenBuffers(1,&output);
    for(size_t fixed:{0U,1U})for(float angle:{.000001F,.7F,3.8F,6.1F})for(float phi:{0.F,1.2F}) {
        nadoc_vr::BendArc arc;arc.a={-.2F,0,-1.3F};arc.length=.6F;
        arc.tangent=glm::normalize(glm::vec3(.2F,.3F,1));
        arc.direction=glm::angleAxis(phi,arc.tangent)*arc.referenceDirection();
        arc.b=arc.a+arc.length*arc.tangent;arc.fixedEnd=fixed;arc.angle=angle;
        const auto origin=arc.a;arc.updateEndpoint();
        const auto binormal=glm::cross(arc.tangent,arc.direction);
        std::vector<Vertex> source;std::vector<glm::vec3> expected;
        for(float t:{-.3F,0.F,.25F,.5F,1.F,1.3F}) {
            const glm::vec3 transverse=arc.direction*.03F+binormal*.02F;
            source.push_back({origin+arc.length*t*arc.tangent+transverse,{},1});
            const float clamped=glm::clamp(t,0.F,1.F);
            const float phase=arc.angle*(fixed?1-clamped:clamped);
            expected.push_back(arc.point(clamped)+arc.endTangent(clamped)*(t-clamped)*arc.length+
                glm::angleAxis(phase,binormal)*transverse);
        }
        glBindBuffer(GL_ARRAY_BUFFER,input);glBufferData(GL_ARRAY_BUFFER,source.size()*sizeof(Vertex),source.data(),GL_STATIC_DRAW);
        glBindBuffer(GL_TRANSFORM_FEEDBACK_BUFFER,output);glBufferData(GL_TRANSFORM_FEEDBACK_BUFFER,expected.size()*sizeof(glm::vec3),nullptr,GL_STREAM_READ);
        glBindBufferBase(GL_TRANSFORM_FEEDBACK_BUFFER,0,output);
        std::array<std::vector<unsigned char>,4> masks;masks[0].assign(source.size(),2);
        points.dirty=true;points.update(masks);points.begin(glm::mat4(1),glm::mat4(1),arc);
        glEnable(GL_RASTERIZER_DISCARD);glBeginTransformFeedback(GL_POINTS);
        points.draw<Vertex>(0,input,offsetof(Vertex,position));glEndTransformFeedback();glDisable(GL_RASTERIZER_DISCARD);points.end();
        std::vector<glm::vec3> actual(expected.size());
        glGetBufferSubData(GL_TRANSFORM_FEEDBACK_BUFFER,0,actual.size()*sizeof(glm::vec3),actual.data());
        for(size_t i=0;i<actual.size();++i)assert(glm::distance(actual[i],expected[i])<2e-5F);
    }
    for(int mode:{1,2})for(float angle:{-7.F,-.4F,0.F,.7F,8.F}) {
        nadoc_vr::BendArc arc;arc.a={-.1F,.02F,-1.4F};arc.length=.6F;
        arc.tangent=glm::normalize(glm::vec3(.2F,.3F,1));arc.angle=angle;
        arc.fixedEnd=1; // Twist always anchors plane 1, independent of Bend state.
        const auto radial=arc.referenceDirection()*.09F;
        const auto rigid=glm::translate(glm::mat4(1),glm::vec3(.1F,.2F,-.03F))*
            glm::rotate(glm::mat4(1),angle,glm::normalize(glm::vec3(1,2,3)));
        const auto model=glm::translate(glm::mat4(1),glm::vec3(.3F,-.2F,.1F));
        std::vector<Vertex> source;std::vector<glm::vec3> expected;
        for(float t:{-.3F,0.F,.25F,.5F,1.F,1.3F}) {
            const auto p=arc.a+arc.tangent*arc.length*t+radial;
            source.push_back({p,{},1});
            const auto twisted=arc.a+arc.tangent*arc.length*t+
                glm::angleAxis(angle*glm::clamp(t,0.F,1.F),arc.tangent)*radial;
            expected.push_back(glm::vec3(model*(mode==1?glm::vec4(twisted,1):rigid*glm::vec4(p,1))));
        }
        glBindBuffer(GL_ARRAY_BUFFER,input);glBufferData(GL_ARRAY_BUFFER,source.size()*sizeof(Vertex),source.data(),GL_STATIC_DRAW);
        glBindBuffer(GL_TRANSFORM_FEEDBACK_BUFFER,output);glBufferData(GL_TRANSFORM_FEEDBACK_BUFFER,expected.size()*sizeof(glm::vec3),nullptr,GL_STREAM_READ);
        glBindBufferBase(GL_TRANSFORM_FEEDBACK_BUFFER,0,output);
        std::array<std::vector<unsigned char>,4> masks;masks[0].assign(source.size(),2);
        points.dirty=true;points.update(masks);points.begin(glm::mat4(1),model,arc,mode,rigid);
        glEnable(GL_RASTERIZER_DISCARD);glBeginTransformFeedback(GL_POINTS);
        points.draw<Vertex>(0,input,offsetof(Vertex,position));glEndTransformFeedback();glDisable(GL_RASTERIZER_DISCARD);points.end();
        std::vector<glm::vec3> actual(expected.size());
        glGetBufferSubData(GL_TRANSFORM_FEEDBACK_BUFFER,0,actual.size()*sizeof(glm::vec3),actual.data());
        for(size_t i=0;i<actual.size();++i)assert(glm::distance(actual[i],expected[i])<2e-5F);
    }
    glDeleteBuffers(1,&input);glDeleteBuffers(1,&output);
    SceneData data;data.available.fill(true);ColorSet colors;
    for(auto& c:colors.values)c={.8F,.2F,.3F};
    for(auto& rep:data.representations)for(int i=0;i<100;++i) {
        const auto id="point"+std::to_string(i);
        rep.points.push_back({id,{.08F,0,-1.6F+i*.006F},colors,.002F});
        rep.ownerAliases.push_back({id,{"selected"}});
    }
    GlScene scene(std::move(data),false,{}, {},false);
    scene.setSelectionHighlights({}, {},{"selected"},{});
    nadoc_vr::BendArc arc;arc.a={0,0,-1.6F};arc.b={0,0,-1};arc.length=.6F;arc.angle=1.2F;arc.updateEndpoint();
    scene.setBendPointArc(arc);
    auto vp=glm::ortho(-.45F,.45F,-.45F,.45F,.01F,10.F)*glm::lookAt(glm::vec3(.2F,-2,-1.3F),glm::vec3(.2F,0,-1.3F),glm::vec3(0,0,1));
    auto render=[&](const glm::mat4& matrix) {
        glViewport(0,0,128,128);glClearColor(0,0,0,1);glClear(GL_COLOR_BUFFER_BIT|GL_DEPTH_BUFFER_BIT);
        scene.renderBendPoints(matrix,glm::mat4(1));
        std::vector<unsigned char> pixels(128*128*3);glReadPixels(0,0,128,128,GL_RGB,GL_UNSIGNED_BYTE,pixels.data());return pixels;
    };
    const auto visible=render(vp);
    auto cyan=[](const auto& pixels){size_t n=0;for(size_t i=0;i<pixels.size();i+=3)n+=pixels[i+1]>200 && pixels[i+2]>150 && pixels[i]<100;return n;};
    assert(cyan(visible)>100);
    assert(cyan(render(vp*glm::translate(glm::mat4(1),glm::vec3(10,0,0))))==0);
    scene.setSelectionHighlights({}, {},{},{});assert(cyan(render(vp))==0);
    scene.setSelectionHighlights({}, {},{"selected"},{});scene.setBendPointArc(std::nullopt);assert(cyan(render(vp))==0);
    std::ofstream ppm(directory+"/bend-point-cloud.ppm",std::ios::binary);ppm<<"P6\n128 128\n255\n";
    for(int y=127;y>=0;--y)ppm.write(reinterpret_cast<const char*>(visible.data()+y*128*3),128*3);
    for(int mode:{1,2}) {
        scene.setBendPointArc(mode==1?std::optional{arc}:std::nullopt,true);
        scene.setMovePointPreview(mode==2?std::vector<std::string>{"selected"}:std::vector<std::string>{},
            glm::translate(glm::mat4(1),glm::vec3(.15F,0,0)));
        const auto image=render(vp);assert(cyan(image)>100);
        assert(cyan(render(vp*glm::translate(glm::mat4(1),glm::vec3(10,0,0))))==0);
        scene.setSelectionHighlights({}, {},{},{});assert(cyan(render(vp))==0);
        scene.setSelectionHighlights({}, {},{"selected"},{});
        scene.setBendPointArc(std::nullopt);scene.setMovePointPreview({},glm::mat4(1));
        assert(cyan(render(vp))==0);
        std::ofstream out(directory+(mode==1?"/twist-point-cloud.ppm":"/move-point-cloud.ppm"),std::ios::binary);
        out<<"P6\n128 128\n255\n";
        for(int y=127;y>=0;--y)out.write(reinterpret_cast<const char*>(image.data()+y*128*3),128*3);
    }
    assert(glGetError()==GL_NO_ERROR);
    std::cout<<"Bend point shader: both anchors, tails, rotated basis, >180 degrees, bounded selection and visible/absent pixels passed\n";
}

int bendPointBenchmark(const char* snapshot,const char* representation,const char* output,const std::string& tool="bend") {
    auto data=loadScene(snapshot);const auto rep=representationFromName(representation);data.initialRepresentation=rep;
    const auto& source=data.representations[representationSourceIndex(rep)];
    std::vector<std::string> owners;for(const auto& h:source.ownerHandles)owners.push_back(h.token);
    assert(!owners.empty());
    glm::vec3 lo(1e6F),hi(-1e6F);const auto axis=data.sourceAxes[2];
    float low=1e6F,high=-1e6F;
    auto include=[&](glm::vec3 p){lo=glm::min(lo,p);hi=glm::max(hi,p);low=std::min(low,glm::dot(p,axis));high=std::max(high,glm::dot(p,axis));};
    for(const auto& p:source.points)include(p.position);
    for(const auto& p:source.boxes)include(p.center);
    for(const auto& c:source.cylinders){include(c.start);include(c.end);}
    const auto center=(lo+hi)*.5F;
    nadoc_vr::BendArc arc;arc.tangent=axis;arc.sourceAxes=data.sourceAxes;arc.direction=arc.referenceDirection();
    arc.a=center+axis*(low-glm::dot(center,axis));arc.length=high-low;arc.b=arc.a+axis*arc.length;
    GlScene scene(std::move(data),false,{}, {},false);scene.setSelectionHighlights({}, {},owners,{});
    const float extent=std::max(glm::length(hi-lo),.2F)*.8F;
    const auto vp=glm::ortho(-extent,extent,-extent*2056/1852,extent*2056/1852,.01F,10.F)*
        glm::lookAt(center+glm::cross(axis,arc.direction)*2.F,center,axis);
    // An invisible desktop window can be clamped to the monitor height. Use a
    // real headset-sized FBO so every measured pixel is actually rendered.
    GLuint fbo,color,depth;glGenFramebuffers(1,&fbo);glBindFramebuffer(GL_FRAMEBUFFER,fbo);
    glGenTextures(1,&color);glBindTexture(GL_TEXTURE_2D,color);glTexImage2D(GL_TEXTURE_2D,0,GL_RGBA8,1852,2056,0,GL_RGBA,GL_UNSIGNED_BYTE,nullptr);
    glFramebufferTexture2D(GL_FRAMEBUFFER,GL_COLOR_ATTACHMENT0,GL_TEXTURE_2D,color,0);
    glGenRenderbuffers(1,&depth);glBindRenderbuffer(GL_RENDERBUFFER,depth);glRenderbufferStorage(GL_RENDERBUFFER,GL_DEPTH_COMPONENT24,1852,2056);
    glFramebufferRenderbuffer(GL_FRAMEBUFFER,GL_DEPTH_ATTACHMENT,GL_RENDERBUFFER,depth);
    assert(glCheckFramebufferStatus(GL_FRAMEBUFFER)==GL_FRAMEBUFFER_COMPLETE);
    GLuint query;glGenQueries(1,&query);glEnable(GL_DEPTH_TEST);glfwSwapInterval(0);
    auto stats=[](const char* name,std::vector<double> v){std::sort(v.begin(),v.end());std::cout<<" "<<name<<"_p50_ms="<<v[v.size()/2]<<" "<<name<<"_p95_ms="<<v[size_t(v.size()*.95)]<<" "<<name<<"_max_ms="<<v.back();};
    for(int mode=0;mode<3;++mode) {
        std::vector<double> gpu,cpu;
        for(int i=0;i<130;++i) {
            arc.angle=glm::radians(60.F+30.F*std::sin(i*.08F));arc.updateEndpoint();
            if(tool=="twist")arc.angle=glm::radians(180.F*std::sin(i*.08F));
            scene.setBendPointArc(mode && tool!="move"?std::optional{arc}:std::nullopt,tool=="twist");
            scene.setMovePointPreview(mode && tool=="move"?owners:std::vector<std::string>{},
                glm::translate(glm::mat4(1),center+glm::vec3(.05F*std::sin(i*.08F),0,0))*
                glm::rotate(glm::mat4(1),.3F*std::sin(i*.08F),axis)*glm::translate(glm::mat4(1),-center));
            const auto start=std::chrono::steady_clock::now();glBeginQuery(GL_TIME_ELAPSED,query);
            if(mode!=2)scene.renderShadowMap(glm::mat4(1),{{.577F,.577F,.577F},{0,1,0}});
            glBindFramebuffer(GL_FRAMEBUFFER,fbo);glDrawBuffer(GL_COLOR_ATTACHMENT0);glViewport(0,0,1852,2056);
            for(int eye=0;eye<2;++eye) {
                glClearColor(.015F,.025F,.045F,1);glClear(GL_COLOR_BUFFER_BIT|GL_DEPTH_BUFFER_BIT);
                if(mode==2)scene.renderBendPoints(vp,glm::mat4(1));else scene.render(vp,glm::mat4(1),{});
            }
            glEndQuery(GL_TIME_ELAPSED);const auto submitted=std::chrono::steady_clock::now();
            GLuint64 ns;glGetQueryObjectui64v(query,GL_QUERY_RESULT,&ns);
            if(i>=10){gpu.push_back(double(ns)/1e6);cpu.push_back(std::chrono::duration<double,std::milli>(submitted-start).count());}
        }
        std::cout<<"POINT_BENCH tool="<<tool<<" rep="<<representation<<" mode="<<mode<<" points="<<(tool=="move"?scene.movePointCount():scene.bendPointCount())<<" samples="<<gpu.size();stats("gpu",gpu);stats("cpu",cpu);std::cout<<std::endl;
        std::vector<unsigned char> pixels(1852*2056*3);glReadPixels(0,0,1852,2056,GL_RGB,GL_UNSIGNED_BYTE,pixels.data());
        std::ofstream ppm(std::string(output)+"-"+std::to_string(mode)+".ppm",std::ios::binary);ppm<<"P6\n1852 2056\n255\n";
        for(int y=2055;y>=0;--y)ppm.write(reinterpret_cast<const char*>(pixels.data()+y*1852*3),1852*3);
    }
    glDeleteQueries(1,&query);glBindFramebuffer(GL_FRAMEBUFFER,0);glDeleteFramebuffers(1,&fbo);glDeleteTextures(1,&color);glDeleteRenderbuffers(1,&depth);assert(glGetError()==GL_NO_ERROR);return 0;
}
