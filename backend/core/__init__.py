"""IrisFlow 核心模块。

提供系统信息、版本、运行状态等基础接口。
"""

from fastapi import APIRouter

from core.info import router as info_router

router = APIRouter()
router.include_router(info_router)

__all__ = ["router"]
