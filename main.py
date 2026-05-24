import sys
import runpy

if __name__ == "__main__":
    runpy.run_module("spider.spider", run_name="__main__")
else:
    from spider import spider as _spider

    sys.modules[__name__] = _spider
