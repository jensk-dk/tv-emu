/*
 * A Vulkan layer for the target: programs that draw on the host's GPU through
 * the virtual GPU (Mesa's Venus driver) are not offered window formats with
 * 16 bits a channel.
 *
 * Why: such a program hands its pictures to the compositor as GPU buffers,
 * and the compositor draws through the same virtual GPU's OpenGL ES side,
 * where the host has to take each buffer into its own OpenGL ES. Not every
 * host driver takes a 16-bit buffer there (NVIDIA's does not: no layout for
 * the format ABGR16161616), the target cannot ask, and one refused buffer
 * ends the compositor's drawing for good. A program that picks the deepest
 * format on offer (mpv does) would end the display for all programs. The
 * 8-bit and 10-bit formats stay, and those are what a TV picture needs.
 *
 * Installed as an implicit layer (emu_vulkan_formats.json), so it is there
 * for every program; EMU_VULKAN_ALL_FORMATS=1 turns it off. Other Vulkan
 * devices (the target's CPU renderer) are left as they are.
 */
#include <stdlib.h>
#include <string.h>
#include <pthread.h>
#include <vulkan/vulkan.h>
#include <vulkan/vk_layer.h>

#define VENUS_NAME "Virtio-GPU Venus"
#define SLOTS 64

struct instance_entry {
    void *key;
    VkInstance instance;
    PFN_vkGetInstanceProcAddr next;
    PFN_vkDestroyInstance destroy;
    PFN_vkGetPhysicalDeviceProperties properties;
    PFN_vkGetPhysicalDeviceSurfaceFormatsKHR formats;
    PFN_vkGetPhysicalDeviceSurfaceFormats2KHR formats2;
};

struct device_entry {
    void *key;
    PFN_vkGetDeviceProcAddr next;
    PFN_vkDestroyDevice destroy;
};

static struct instance_entry instances[SLOTS];
static struct device_entry devices[SLOTS];
static pthread_mutex_t lock = PTHREAD_MUTEX_INITIALIZER;

/* The loader's dispatch table, which an instance shares with its physical
 * devices: the first pointer in every such handle. */
static void *key_of(void *handle)
{
    return *(void **)handle;
}

static struct instance_entry *instance_of(void *handle)
{
    void *key = key_of(handle);
    struct instance_entry *found = NULL;
    pthread_mutex_lock(&lock);
    for (int i = 0; i < SLOTS; i++)
        if (instances[i].key == key)
            found = &instances[i];
    pthread_mutex_unlock(&lock);
    return found;
}

static struct device_entry *device_of(void *handle)
{
    void *key = key_of(handle);
    struct device_entry *found = NULL;
    pthread_mutex_lock(&lock);
    for (int i = 0; i < SLOTS; i++)
        if (devices[i].key == key)
            found = &devices[i];
    pthread_mutex_unlock(&lock);
    return found;
}

static int hidden(const struct instance_entry *entry, VkPhysicalDevice device, VkFormat format)
{
    VkPhysicalDeviceProperties properties;
    switch (format) {
    case VK_FORMAT_R16G16B16_UNORM:
    case VK_FORMAT_R16G16B16A16_UNORM:
        break;
    default:
        return 0;
    }
    entry->properties(device, &properties);
    return strncmp(properties.deviceName, VENUS_NAME, strlen(VENUS_NAME)) == 0;
}

static VKAPI_ATTR VkResult VKAPI_CALL surface_formats(VkPhysicalDevice device, VkSurfaceKHR surface, uint32_t *count,
                                                      VkSurfaceFormatKHR *formats)
{
    struct instance_entry *entry = instance_of(device);
    uint32_t all = 0, kept = 0;
    VkSurfaceFormatKHR *found;
    VkResult result = entry->formats(device, surface, &all, NULL);
    if (result != VK_SUCCESS || !all) {
        if (result == VK_SUCCESS)
            *count = 0;
        return result;
    }
    found = calloc(all, sizeof(*found));
    if (!found)
        return VK_ERROR_OUT_OF_HOST_MEMORY;
    result = entry->formats(device, surface, &all, found);
    if (result != VK_SUCCESS && result != VK_INCOMPLETE) {
        free(found);
        return result;
    }
    result = VK_SUCCESS;
    for (uint32_t i = 0; i < all; i++) {
        if (hidden(entry, device, found[i].format))
            continue;
        if (formats) {
            if (kept == *count) {
                result = VK_INCOMPLETE;
                break;
            }
            formats[kept] = found[i];
        }
        kept++;
    }
    *count = kept;
    free(found);
    return result;
}

static VKAPI_ATTR VkResult VKAPI_CALL surface_formats2(VkPhysicalDevice device,
                                                       const VkPhysicalDeviceSurfaceInfo2KHR *info, uint32_t *count,
                                                       VkSurfaceFormat2KHR *formats)
{
    struct instance_entry *entry = instance_of(device);
    uint32_t all = 0, kept = 0;
    VkSurfaceFormat2KHR *found;
    VkResult result = entry->formats2(device, info, &all, NULL);
    if (result != VK_SUCCESS || !all) {
        if (result == VK_SUCCESS)
            *count = 0;
        return result;
    }
    found = calloc(all, sizeof(*found));
    if (!found)
        return VK_ERROR_OUT_OF_HOST_MEMORY;
    for (uint32_t i = 0; i < all; i++)
        found[i].sType = VK_STRUCTURE_TYPE_SURFACE_FORMAT_2_KHR;
    result = entry->formats2(device, info, &all, found);
    if (result != VK_SUCCESS && result != VK_INCOMPLETE) {
        free(found);
        return result;
    }
    if (formats) {
        /* Once more, with what the caller chained to its entries at the
         * places of the formats it will get, so that those get filled. */
        for (uint32_t i = 0; i < all; i++) {
            if (hidden(entry, device, found[i].surfaceFormat.format))
                continue;
            if (kept < *count)
                found[i].pNext = formats[kept].pNext;
            kept++;
        }
        result = entry->formats2(device, info, &all, found);
        if (result != VK_SUCCESS && result != VK_INCOMPLETE) {
            free(found);
            return result;
        }
        kept = 0;
    }
    result = VK_SUCCESS;
    for (uint32_t i = 0; i < all; i++) {
        if (hidden(entry, device, found[i].surfaceFormat.format))
            continue;
        if (formats) {
            if (kept == *count) {
                result = VK_INCOMPLETE;
                break;
            }
            formats[kept].surfaceFormat = found[i].surfaceFormat;
        }
        kept++;
    }
    *count = kept;
    free(found);
    return result;
}

static VKAPI_ATTR VkResult VKAPI_CALL create_instance(const VkInstanceCreateInfo *info,
                                                      const VkAllocationCallbacks *allocator, VkInstance *instance)
{
    VkLayerInstanceCreateInfo *link = (VkLayerInstanceCreateInfo *)info->pNext;
    PFN_vkGetInstanceProcAddr next;
    PFN_vkCreateInstance create;
    VkResult result;
    while (link && !(link->sType == VK_STRUCTURE_TYPE_LOADER_INSTANCE_CREATE_INFO && link->function == VK_LAYER_LINK_INFO))
        link = (VkLayerInstanceCreateInfo *)link->pNext;
    if (!link || !link->u.pLayerInfo)
        return VK_ERROR_INITIALIZATION_FAILED;
    next = link->u.pLayerInfo->pfnNextGetInstanceProcAddr;
    link->u.pLayerInfo = link->u.pLayerInfo->pNext;
    create = (PFN_vkCreateInstance)next(VK_NULL_HANDLE, "vkCreateInstance");
    if (!create)
        return VK_ERROR_INITIALIZATION_FAILED;
    result = create(info, allocator, instance);
    if (result != VK_SUCCESS)
        return result;
    pthread_mutex_lock(&lock);
    for (int i = 0; i < SLOTS; i++) {
        struct instance_entry *entry = &instances[i];
        if (entry->key)
            continue;
        entry->instance = *instance;
        entry->next = next;
        entry->destroy = (PFN_vkDestroyInstance)next(*instance, "vkDestroyInstance");
        entry->properties = (PFN_vkGetPhysicalDeviceProperties)next(*instance, "vkGetPhysicalDeviceProperties");
        entry->formats = (PFN_vkGetPhysicalDeviceSurfaceFormatsKHR)next(*instance,
                                                                        "vkGetPhysicalDeviceSurfaceFormatsKHR");
        entry->formats2 = (PFN_vkGetPhysicalDeviceSurfaceFormats2KHR)next(*instance,
                                                                          "vkGetPhysicalDeviceSurfaceFormats2KHR");
        entry->key = key_of(*instance);
        break;
    }
    pthread_mutex_unlock(&lock);
    return VK_SUCCESS;
}

static VKAPI_ATTR void VKAPI_CALL destroy_instance(VkInstance instance, const VkAllocationCallbacks *allocator)
{
    struct instance_entry *entry = instance ? instance_of(instance) : NULL;
    PFN_vkDestroyInstance destroy;
    if (!entry)
        return;
    destroy = entry->destroy;
    pthread_mutex_lock(&lock);
    memset(entry, 0, sizeof(*entry));
    pthread_mutex_unlock(&lock);
    destroy(instance, allocator);
}

static VKAPI_ATTR VkResult VKAPI_CALL create_device(VkPhysicalDevice physical, const VkDeviceCreateInfo *info,
                                                    const VkAllocationCallbacks *allocator, VkDevice *device)
{
    VkLayerDeviceCreateInfo *link = (VkLayerDeviceCreateInfo *)info->pNext;
    PFN_vkGetInstanceProcAddr next_instance;
    PFN_vkGetDeviceProcAddr next;
    PFN_vkCreateDevice create;
    struct instance_entry *entry = instance_of(physical);
    VkResult result;
    while (link && !(link->sType == VK_STRUCTURE_TYPE_LOADER_DEVICE_CREATE_INFO && link->function == VK_LAYER_LINK_INFO))
        link = (VkLayerDeviceCreateInfo *)link->pNext;
    if (!link || !link->u.pLayerInfo)
        return VK_ERROR_INITIALIZATION_FAILED;
    next_instance = link->u.pLayerInfo->pfnNextGetInstanceProcAddr;
    next = link->u.pLayerInfo->pfnNextGetDeviceProcAddr;
    link->u.pLayerInfo = link->u.pLayerInfo->pNext;
    create = (PFN_vkCreateDevice)next_instance(entry ? entry->instance : VK_NULL_HANDLE, "vkCreateDevice");
    if (!create)
        return VK_ERROR_INITIALIZATION_FAILED;
    result = create(physical, info, allocator, device);
    if (result != VK_SUCCESS)
        return result;
    pthread_mutex_lock(&lock);
    for (int i = 0; i < SLOTS; i++) {
        if (devices[i].key)
            continue;
        devices[i].next = next;
        devices[i].destroy = (PFN_vkDestroyDevice)next(*device, "vkDestroyDevice");
        devices[i].key = key_of(*device);
        break;
    }
    pthread_mutex_unlock(&lock);
    return VK_SUCCESS;
}

static VKAPI_ATTR void VKAPI_CALL destroy_device(VkDevice device, const VkAllocationCallbacks *allocator)
{
    struct device_entry *entry = device ? device_of(device) : NULL;
    PFN_vkDestroyDevice destroy;
    if (!entry)
        return;
    destroy = entry->destroy;
    pthread_mutex_lock(&lock);
    memset(entry, 0, sizeof(*entry));
    pthread_mutex_unlock(&lock);
    destroy(device, allocator);
}

#define EXPORTED __attribute__((visibility("default")))

EXPORTED VKAPI_ATTR PFN_vkVoidFunction VKAPI_CALL emu_formats_device_proc(VkDevice device, const char *name);

EXPORTED VKAPI_ATTR PFN_vkVoidFunction VKAPI_CALL emu_formats_instance_proc(VkInstance instance, const char *name)
{
    struct instance_entry *entry;
    if (!strcmp(name, "vkGetInstanceProcAddr"))
        return (PFN_vkVoidFunction)emu_formats_instance_proc;
    if (!strcmp(name, "vkCreateInstance"))
        return (PFN_vkVoidFunction)create_instance;
    if (!strcmp(name, "vkDestroyInstance"))
        return (PFN_vkVoidFunction)destroy_instance;
    if (!strcmp(name, "vkCreateDevice"))
        return (PFN_vkVoidFunction)create_device;
    if (!strcmp(name, "vkDestroyDevice"))
        return (PFN_vkVoidFunction)destroy_device;
    if (!strcmp(name, "vkGetDeviceProcAddr"))
        return (PFN_vkVoidFunction)emu_formats_device_proc;
    entry = instance ? instance_of(instance) : NULL;
    if (!entry)
        return NULL;
    /* Only what the instance below has is offered, as a program would see
     * it without this layer. */
    if (!strcmp(name, "vkGetPhysicalDeviceSurfaceFormatsKHR") && entry->formats && entry->properties)
        return (PFN_vkVoidFunction)surface_formats;
    if (!strcmp(name, "vkGetPhysicalDeviceSurfaceFormats2KHR") && entry->formats2 && entry->properties)
        return (PFN_vkVoidFunction)surface_formats2;
    return entry->next(instance, name);
}

EXPORTED VKAPI_ATTR PFN_vkVoidFunction VKAPI_CALL emu_formats_device_proc(VkDevice device, const char *name)
{
    struct device_entry *entry;
    if (!strcmp(name, "vkGetDeviceProcAddr"))
        return (PFN_vkVoidFunction)emu_formats_device_proc;
    if (!strcmp(name, "vkDestroyDevice"))
        return (PFN_vkVoidFunction)destroy_device;
    entry = device ? device_of(device) : NULL;
    return entry ? entry->next(device, name) : NULL;
}

EXPORTED VKAPI_ATTR VkResult VKAPI_CALL emu_formats_negotiate(VkNegotiateLayerInterface *interface)
{
    if (!interface || interface->sType != LAYER_NEGOTIATE_INTERFACE_STRUCT || interface->loaderLayerInterfaceVersion < 2)
        return VK_ERROR_INITIALIZATION_FAILED;
    interface->loaderLayerInterfaceVersion = 2;
    interface->pfnGetInstanceProcAddr = emu_formats_instance_proc;
    interface->pfnGetDeviceProcAddr = emu_formats_device_proc;
    interface->pfnGetPhysicalDeviceProcAddr = NULL;
    return VK_SUCCESS;
}
