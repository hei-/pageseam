from dify_plugin import DifyPluginEnv, Plugin

# 30 页扫描件在纯 CPU 上需要几分钟，工具内部会轮询等待，这里放宽单次调用超时
plugin = Plugin(DifyPluginEnv(MAX_REQUEST_TIMEOUT=600))

if __name__ == "__main__":
    plugin.run()
