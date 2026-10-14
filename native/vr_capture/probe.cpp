// Independent X11 Vulkan diagnostic pattern. No headset/runtime mutation.
// Frame index is encoded exactly into B,G,R bytes of every pixel (UNORM).
#define VK_USE_PLATFORM_XLIB_KHR
#include <vulkan/vulkan.h>
#include <X11/Xlib.h>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>
#define CHECK(expr) do { VkResult r=(expr); if(r!=VK_SUCCESS) throw std::runtime_error(std::string(#expr)+": "+std::to_string(r)); } while(0)
int main(int argc,char** argv) {
  try {
    double seconds=argc>1?std::atof(argv[1]):4.0;
    unsigned width=argc>2?std::strtoul(argv[2],nullptr,10):640;
    unsigned height=argc>3?std::strtoul(argv[3],nullptr,10):480;
    double captureSeconds=argc>4?std::max(.1,std::atof(argv[4])):std::max(.1,seconds-1);
    Display* display=XOpenDisplay(nullptr); if(!display) throw std::runtime_error("No X display");
    Window window=XCreateSimpleWindow(display,DefaultRootWindow(display),10,10,width,height,0,0,0);
    XStoreName(display,window,"NADOC Vulkan capture calibration (synthetic pixels)"); XMapWindow(display,window); XFlush(display);
    const char* extensions[]={VK_KHR_SURFACE_EXTENSION_NAME,VK_KHR_XLIB_SURFACE_EXTENSION_NAME};
    VkApplicationInfo app{VK_STRUCTURE_TYPE_APPLICATION_INFO}; app.pApplicationName="nadoc_capture_probe"; app.apiVersion=VK_API_VERSION_1_1;
    VkInstanceCreateInfo ic{VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO}; ic.pApplicationInfo=&app; ic.enabledExtensionCount=2; ic.ppEnabledExtensionNames=extensions;
    VkInstance instance{}; CHECK(vkCreateInstance(&ic,nullptr,&instance));
    VkXlibSurfaceCreateInfoKHR sc{VK_STRUCTURE_TYPE_XLIB_SURFACE_CREATE_INFO_KHR}; sc.dpy=display; sc.window=window;
    VkSurfaceKHR surface{}; CHECK(vkCreateXlibSurfaceKHR(instance,&sc,nullptr,&surface));
    uint32_t count=0; CHECK(vkEnumeratePhysicalDevices(instance,&count,nullptr)); std::vector<VkPhysicalDevice> devices(count); CHECK(vkEnumeratePhysicalDevices(instance,&count,devices.data()));
    VkPhysicalDevice physical{}; uint32_t family=0;
    for(auto p:devices) { uint32_t n=0; vkGetPhysicalDeviceQueueFamilyProperties(p,&n,nullptr); std::vector<VkQueueFamilyProperties> fs(n); vkGetPhysicalDeviceQueueFamilyProperties(p,&n,fs.data());
      for(uint32_t f=0;f<n;f++) { VkBool32 support=false; vkGetPhysicalDeviceSurfaceSupportKHR(p,f,surface,&support); if(support && fs[f].queueFlags&VK_QUEUE_GRAPHICS_BIT) { physical=p; family=f; break; } } if(physical) break;
    }
    if(!physical) throw std::runtime_error("No graphics/present queue");
    float priority=1; VkDeviceQueueCreateInfo qi{VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO}; qi.queueFamilyIndex=family; qi.queueCount=1; qi.pQueuePriorities=&priority;
    const char* de=VK_KHR_SWAPCHAIN_EXTENSION_NAME;
    VkDeviceCreateInfo dc{VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO}; dc.queueCreateInfoCount=1; dc.pQueueCreateInfos=&qi; dc.enabledExtensionCount=1; dc.ppEnabledExtensionNames=&de;
    VkDevice device{}; CHECK(vkCreateDevice(physical,&dc,nullptr,&device)); VkQueue queue{}; vkGetDeviceQueue(device,family,0,&queue);
    VkSurfaceCapabilitiesKHR caps{}; CHECK(vkGetPhysicalDeviceSurfaceCapabilitiesKHR(physical,surface,&caps));
    uint32_t nf=0; vkGetPhysicalDeviceSurfaceFormatsKHR(physical,surface,&nf,nullptr); std::vector<VkSurfaceFormatKHR> formats(nf); vkGetPhysicalDeviceSurfaceFormatsKHR(physical,surface,&nf,formats.data());
    VkSurfaceFormatKHR format=formats[0]; for(auto f:formats) if(f.format==VK_FORMAT_B8G8R8A8_UNORM) format=f;
    if(format.format!=VK_FORMAT_B8G8R8A8_UNORM && format.format!=VK_FORMAT_R8G8B8A8_UNORM) throw std::runtime_error("Probe needs exact UNORM output");
    VkSwapchainCreateInfoKHR sw{VK_STRUCTURE_TYPE_SWAPCHAIN_CREATE_INFO_KHR}; sw.surface=surface; sw.minImageCount=std::max(3u,caps.minImageCount); if(caps.maxImageCount) sw.minImageCount=std::min(sw.minImageCount,caps.maxImageCount);
    sw.imageFormat=format.format; sw.imageColorSpace=format.colorSpace; sw.imageExtent=caps.currentExtent.width==UINT32_MAX?VkExtent2D{640,480}:caps.currentExtent; sw.imageArrayLayers=1; sw.imageUsage=VK_IMAGE_USAGE_TRANSFER_DST_BIT;
    sw.imageSharingMode=VK_SHARING_MODE_EXCLUSIVE; sw.preTransform=caps.currentTransform; sw.compositeAlpha=VK_COMPOSITE_ALPHA_OPAQUE_BIT_KHR; sw.presentMode=VK_PRESENT_MODE_FIFO_KHR; sw.clipped=VK_TRUE;
    VkSwapchainKHR swap{}; CHECK(vkCreateSwapchainKHR(device,&sw,nullptr,&swap)); uint32_t ni=0; CHECK(vkGetSwapchainImagesKHR(device,swap,&ni,nullptr)); std::vector<VkImage> images(ni); CHECK(vkGetSwapchainImagesKHR(device,swap,&ni,images.data()));
    VkCommandPoolCreateInfo pc{VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO}; pc.queueFamilyIndex=family; pc.flags=VK_COMMAND_POOL_CREATE_RESET_COMMAND_BUFFER_BIT;
    VkCommandPool pool{}; CHECK(vkCreateCommandPool(device,&pc,nullptr,&pool));
    VkCommandBufferAllocateInfo ca{VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO}; ca.commandPool=pool; ca.level=VK_COMMAND_BUFFER_LEVEL_PRIMARY; ca.commandBufferCount=1;
    VkCommandBuffer command{}; CHECK(vkAllocateCommandBuffers(device,&ca,&command));
    VkSemaphoreCreateInfo se{VK_STRUCTURE_TYPE_SEMAPHORE_CREATE_INFO}; VkSemaphore acquire{}; CHECK(vkCreateSemaphore(device,&se,nullptr,&acquire));
    std::vector<VkSemaphore> done(ni); for(auto& s:done) CHECK(vkCreateSemaphore(device,&se,nullptr,&s));
    VkFenceCreateInfo fc{VK_STRUCTURE_TYPE_FENCE_CREATE_INFO}; fc.flags=VK_FENCE_CREATE_SIGNALED_BIT; VkFence fence{}; CHECK(vkCreateFence(device,&fc,nullptr,&fence));
    auto start=std::chrono::steady_clock::now(); uint32_t frame=0;
    std::string directory=std::getenv("NADOC_VR_CAPTURE_DIR")?std::getenv("NADOC_VR_CAPTURE_DIR"):"";
    std::ofstream expected(directory.empty()?"/dev/null":directory+"/probe-expected.jsonl");
    while(std::chrono::duration<double>(std::chrono::steady_clock::now()-start).count()<seconds) {
      CHECK(vkWaitForFences(device,1,&fence,VK_TRUE,UINT64_MAX)); CHECK(vkResetFences(device,1,&fence));
      uint32_t index=0; CHECK(vkAcquireNextImageKHR(device,swap,UINT64_MAX,acquire,VK_NULL_HANDLE,&index)); CHECK(vkResetCommandBuffer(command,0));
      VkCommandBufferBeginInfo bi{VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO}; CHECK(vkBeginCommandBuffer(command,&bi));
      VkImageMemoryBarrier bar{VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER}; bar.image=images[index]; bar.oldLayout=VK_IMAGE_LAYOUT_UNDEFINED; bar.newLayout=VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL; bar.dstAccessMask=VK_ACCESS_TRANSFER_WRITE_BIT; bar.srcQueueFamilyIndex=bar.dstQueueFamilyIndex=VK_QUEUE_FAMILY_IGNORED; bar.subresourceRange={VK_IMAGE_ASPECT_COLOR_BIT,0,1,0,1};
      vkCmdPipelineBarrier(command,VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT,VK_PIPELINE_STAGE_TRANSFER_BIT,0,0,nullptr,0,nullptr,1,&bar);
      VkClearColorValue color{}; color.float32[0]=(frame&255)/255.f; color.float32[1]=((frame>>8)&255)/255.f; color.float32[2]=((frame^0x5a)&255)/255.f; color.float32[3]=1;
      vkCmdClearColorImage(command,images[index],VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL,&color,1,&bar.subresourceRange);
      bar.srcAccessMask=VK_ACCESS_TRANSFER_WRITE_BIT; bar.dstAccessMask=0; bar.oldLayout=VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL; bar.newLayout=VK_IMAGE_LAYOUT_PRESENT_SRC_KHR;
      vkCmdPipelineBarrier(command,VK_PIPELINE_STAGE_TRANSFER_BIT,VK_PIPELINE_STAGE_BOTTOM_OF_PIPE_BIT,0,0,nullptr,0,nullptr,1,&bar); CHECK(vkEndCommandBuffer(command));
      VkPipelineStageFlags wait=VK_PIPELINE_STAGE_TRANSFER_BIT;
      VkSubmitInfo submit{VK_STRUCTURE_TYPE_SUBMIT_INFO}; submit.waitSemaphoreCount=1; submit.pWaitSemaphores=&acquire; submit.pWaitDstStageMask=&wait; submit.commandBufferCount=1; submit.pCommandBuffers=&command; submit.signalSemaphoreCount=1; submit.pSignalSemaphores=&done[index]; CHECK(vkQueueSubmit(queue,1,&submit,fence));
      VkPresentInfoKHR pi{VK_STRUCTURE_TYPE_PRESENT_INFO_KHR}; pi.waitSemaphoreCount=1; pi.pWaitSemaphores=&done[index]; pi.swapchainCount=1; pi.pSwapchains=&swap; pi.pImageIndices=&index; CHECK(vkQueuePresentKHR(queue,&pi));
      expected<<"{\"frame\":"<<frame<<",\"present\":"<<(frame+1)<<",\"image\":"<<index<<",\"r\":"<<(frame&255)<<",\"g\":"<<((frame>>8)&255)<<",\"b\":"<<((frame^0x5a)&255)<<"}\n"; expected.flush(); frame++;
      // Auto-arm only the synthetic diagnostic, after layer resources warm up.
      if(frame==10 && !directory.empty()) { std::ofstream control(directory+"/control.txt"); control<<"1 "<<captureSeconds<<'\n'; }
    }
    CHECK(vkDeviceWaitIdle(device)); std::this_thread::sleep_for(std::chrono::seconds(2));
    vkDestroyFence(device,fence,nullptr); for(auto s:done) vkDestroySemaphore(device,s,nullptr); vkDestroySemaphore(device,acquire,nullptr); vkDestroyCommandPool(device,pool,nullptr);
    vkDestroySwapchainKHR(device,swap,nullptr); vkDestroyDevice(device,nullptr); vkDestroySurfaceKHR(instance,surface,nullptr);
    // NVIDIA installs Xlib callbacks in its ICD. Close X while that ICD remains
    // loaded; destroying the instance first can leave dangling Xlib callbacks.
    XDestroyWindow(display,window); XCloseDisplay(display); vkDestroyInstance(instance,nullptr);
    std::printf("Probe completed: %u frames\n",frame); return 0;
  } catch(const std::exception& e) { std::fprintf(stderr,"%s\n",e.what()); return 1; }
}
