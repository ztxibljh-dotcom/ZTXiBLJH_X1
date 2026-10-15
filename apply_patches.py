#!/usr/bin/env python3
# 在已 clone 的上游源码目录里打补丁（cwd 必须是源码根）。
import io, sys, re

def load(p):
    with io.open(p, encoding='utf-8', newline='') as f:
        s = f.read()
    return s.replace('\r\n', '\n').replace('\r', '\n')

def save(p, s):
    with io.open(p, 'w', encoding='utf-8', newline='\n') as f:
        f.write(s)

def sub_once(s, anchor, repl, what):
    if s.count(anchor) != 1:
        sys.exit("anchor not unique (%d): %s" % (s.count(anchor), what))
    return s.replace(anchor, repl)

# ---------- Application.mk ----------
save('Application.mk',
     'APP_STL := c++_static\n'
     'APP_CPPFLAGS := -frtti -fexceptions\n'
     'APP_ABI := arm64-v8a\n'
     'APP_PLATFORM := android-25\n')
print("[ok] Application.mk")

# ---------- log.h: 打开 MY_LOG ----------
h = load('log.h')
new = ('#define MY_LOG(fmt, ...) __android_log_print(ANDROID_LOG_INFO , '
       '"il2cpp", "[%zx]" fmt "\\n", (size_t)pthread_self(), ##__VA_ARGS__)\n')
h, n = re.subn(r'#define MY_LOG\(fmt, \.\.\.\)[ \t]*\n', new, h, count=1)
if n != 1:
    sys.exit("log.h MY_LOG anchor not found (%d)" % n)
save('log.h', h)
print("[ok] log.h")

# ---------- bootstrap.cpp ----------
b = load('bootstrap.cpp')

# 1) get_bundle_id(): 截掉 ":" 后缀（:txi 进程用）
old = "    return std::string(bundle_id);"
new = ("    std::string r(bundle_id);\n"
       "    size_t colon = r.find(':');\n"
       "    if (colon != std::string::npos) r = r.substr(0, colon);\n"
       "    return r;")
b = sub_once(b, old, new, "get_bundle_id")
print("[ok] get_bundle_id")

# 2) 在 use_data_dir 之后追加 JNI 包装 useDataDir
anchor = ("    unlink(formal_patch_info_path);\n"
          "    rename(patch_info_path, formal_patch_info_path);\n"
          "    return NULL;\n"
          "}\n")
wrapper = ("\n__attribute__ ((visibility (\"default\")))\n"
           "JNIEXPORT jstring JNICALL Java_io_github_noodle1983_Boostrap_useDataDir\n"
           "  (JNIEnv * jenv, jclass cls, jstring path, jstring useless) {\n"
           "    if (path == NULL) return NULL;\n"
           "    const char* dp = jenv->GetStringUTFChars(path, NULL);\n"
           "    char* ret = use_data_dir(dp, NULL);\n"
           "    jenv->ReleaseStringUTFChars(path, dp);\n"
           "    if (ret != NULL) return jenv->NewStringUTF(ret);\n"
           "    return NULL;\n"
           "}\n")
b = sub_once(b, anchor, anchor + wrapper, "useDataDir wrapper")
print("[ok] useDataDir wrapper")

# 3) 新增 my_fseeko / my_ftello，并整体替换 init_hook()
extra = "\n".join([
 'typedef int (*FseekoType)(FILE *stream, off64_t offset, int whence);',
 'static int my_fseeko(FILE *stream, off64_t offset, int whence) {',
 '    ShadowZip* sz = get_cached_shadowzip(stream);',
 '    return sz ? sz->fseek(stream, offset, whence) : fseeko(stream, offset, whence);',
 '}',
 'typedef off64_t (*FtelloType)(FILE *stream);',
 'static off64_t my_ftello(FILE *stream) {',
 '    ShadowZip* sz = get_cached_shadowzip(stream);',
 '    return sz ? sz->ftell(stream) : ftello(stream);',
 '}',
 '',
])

new_init = "\n".join([
 'static int init_hook() {',
 '    MY_INFO("init_hook start");',
 '    xhook_enable_debug(1);',
 '#define HOOK(lib, symbol) \\',
 '    if(0 != xhook_register(lib, #symbol, (void*)my_##symbol, NULL)){ \\',
 '        MY_ERROR("failed to find function:%s in %s", #symbol, lib); \\',
 '        return -1; \\',
 '    }',
 '    HOOK("libunity.so", fopen);',
 '    HOOK("libunity.so", fseek);',
 '    HOOK("libunity.so", ftell);',
 '    HOOK("libunity.so", fseeko);',
 '    HOOK("libunity.so", ftello);',
 '    HOOK("libunity.so", fread);',
 '    HOOK("libunity.so", fgets);',
 '    HOOK("libunity.so", fclose);',
 '    HOOK("libunity.so", stat);',
 '    HOOK("libunity.so", open);',
 '    HOOK("libunity.so", read);',
 '    HOOK("libunity.so", lseek);',
 '    HOOK("libunity.so", lseek64);',
 '    HOOK("libunity.so", close);',
 '    HOOK("libunity.so", dlopen);',
 '    HOOK("libmain.so", dlopen);',
 '    if(0 != xhook_refresh(0)){',
 '        MY_ERROR("failed to find replace function");',
 '        return -1;',
 '    }',
 '    MY_INFO("init_hook done");',
 '    return 0;',
 '}',
 '',
])

pat = re.compile(r"static int init_hook\(\)\s*\{.*?\n\}\n", re.S)
m = pat.search(b)
if not m:
    sys.exit("init_hook anchor not found")
b = b[:m.start()] + extra + new_init + b[m.end():]
print("[ok] init_hook replaced")

save('bootstrap.cpp', b)
print("ALL PATCHES APPLIED")
