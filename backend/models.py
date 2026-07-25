"""IrisFlow 共享数据模型。

定义跨模块流通的核心数据类型。
各模块从此处导入共享类型，避免模块间直接依赖。
"""

from pydantic import BaseModel, Field


class IntelligenceItem(BaseModel):
    """单条情报条目。

    来自不同信源的原始数据经归一化后的统一表示。
    为未来 SCOUT/PRISM 模块预留。
    """

    source: str = Field(description="信源：github / arxiv / huggingface")
    source_type: str = Field(description="类型：repo / paper / model")
    title: str = Field(description="标题")
    description: str | None = Field(default=None, description="摘要/描述")
    url: str = Field(description="详情链接")
    score: float = Field(default=0.0, description="综合评分")
    published: str | None = Field(default=None, description="发布日期")
    metadata: dict[str, object] = Field(  # pyright: ignore[reportMissingTypeArgument]
        default_factory=dict,
        description="信源特定元数据（stars, downloads, authors 等）",
    )
