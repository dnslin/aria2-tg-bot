import aria2p
from config.settings import ARIA2_HOST, ARIA2_PORT, ARIA2_SECRET

# 初始化 aria2 客户端
aria2 = aria2p.API(
    aria2p.Client(
        host=ARIA2_HOST,
        port=ARIA2_PORT,
        secret=ARIA2_SECRET
    )
) 