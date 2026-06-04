"""项目 API：CRUD + 触发角色/大纲 Agent 生成并落库。"""
from dataclasses import dataclass
from datetime import datetime, timezone
from html import escape
from io import BytesIO
from urllib.parse import quote
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.agents.character_agent import generate_characters
from app.agents.outline_agent import generate_outline, generate_volume_chapters
from app.agents.style_stats import style_text_from_guide
from app.db import get_session
from app.llm.model_resolver import resolve_project_model
from app.memory.retriever import index_chunk
from app.models import Chapter, Character, Foreshadow, MemoryChunk, Project, TruthFile, Volume
from app.schemas import (
    CharacterCreate,
    CharacterGenerateRequest,
    CharacterOut,
    CharacterUpdate,
    ChapterOutlineUpdate,
    OutlineFillRequest,
    OutlineGenerateRequest,
    ProjectContinuationAnchorUpdate,
    ProjectCreate,
    ProjectDetail,
    ProjectModelUpdate,
    ProjectOut,
    VolumeOut,
)

router = APIRouter(prefix="/api/projects", tags=["projects"])


@dataclass(frozen=True)
class ExportOptions:
    include_metadata: bool = True
    include_reviews: bool = False
    include_references: bool = False
    include_drafts: bool = True


async def _get_project_or_404(session: AsyncSession, project_id: str) -> Project:
    project = await session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    return project


async def _get_project_detail_or_404(session: AsyncSession, project_id: str) -> Project:
    result = await session.execute(
        select(Project)
        .where(Project.id == project_id)
        .options(
            selectinload(Project.volumes)
            .selectinload(Volume.chapters)
            .selectinload(Chapter.summary_row),
            selectinload(Project.volumes)
            .selectinload(Volume.chapters)
            .selectinload(Chapter.reviews),
            selectinload(Project.characters),
            selectinload(Project.settings),
            selectinload(Project.foreshadows),
            selectinload(Project.truth_files),
        )
    )
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    return project


def _single_line(text: str, fallback: str) -> str:
    value = " ".join((text or "").split()).strip()
    return value or fallback


def _is_novel_volume(volume: Volume) -> bool:
    return (getattr(volume, "kind", "novel") or "novel") == "novel"


def _novel_volumes(volumes: list[Volume]) -> list[Volume]:
    return [volume for volume in sorted(volumes, key=lambda v: v.order_index) if _is_novel_volume(volume)]


def _reference_volumes(volumes: list[Volume]) -> list[Volume]:
    return [volume for volume in sorted(volumes, key=lambda v: v.order_index) if not _is_novel_volume(volume)]


def _export_chapters(volume: Volume, options: ExportOptions) -> list[Chapter]:
    chapters = sorted(volume.chapters, key=lambda ch: ch.order_index)
    if options.include_drafts:
        return chapters
    return [chapter for chapter in chapters if (chapter.content or "").strip()]


def _volume_has_export_content(volume: Volume, options: ExportOptions) -> bool:
    if _export_chapters(volume, options):
        return True
    return options.include_drafts and bool((volume.outline or "").strip())


def _markdown_review_lines(chapter: Chapter) -> list[str]:
    review = chapter.latest_review
    if review is None:
        return []
    lines: list[str] = ["**审校报告**", ""]
    if review.summary:
        lines.append(f"- 摘要：{review.summary}")
    lines.append(f"- AI 味评分：{review.ai_flavor_score}")
    if review.model:
        lines.append(f"- 模型：{review.model}")
    if review.issues:
        lines.append("- 问题：")
        for issue in review.issues[:20]:
            if not isinstance(issue, dict):
                continue
            severity = issue.get("severity") or "medium"
            issue_type = issue.get("type") or "issue"
            location = issue.get("location") or ""
            description = issue.get("description") or ""
            suggestion = issue.get("suggestion") or ""
            detail = f"  - [{severity}/{issue_type}]"
            if location:
                detail += f" {location}"
            if description:
                detail += f"：{description}"
            if suggestion:
                detail += f"；建议：{suggestion}"
            lines.append(detail)
    lines.append("")
    return lines


def _append_markdown_volume(lines: list[str], volume: Volume, options: ExportOptions, reference: bool = False) -> None:
    chapters = _export_chapters(volume, options)
    if not chapters and not _volume_has_export_content(volume, options):
        return
    if reference:
        lines.extend([f"### 参考资料 · {_single_line(volume.title, '未命名资料组')}", ""])
    else:
        lines.extend([f"### 第 {volume.order_index + 1} 卷 · {_single_line(volume.title, '未命名卷')}", ""])
    if volume.outline and options.include_drafts:
        label = "资料说明" if reference else "卷纲"
        lines.extend([f"> {label}：{volume.outline.strip()}", ""])
    if not chapters:
        lines.extend(["_本卷还没有章节。_", ""])
        return
    for chapter in chapters:
        chapter_label = "资料" if reference else f"第 {chapter.order_index + 1} 章"
        lines.extend([f"#### {chapter_label} · {_single_line(chapter.title, '未命名章节')}", ""])
        content = (chapter.content or "").strip()
        if content:
            lines.extend([content, ""])
        elif options.include_drafts and chapter.outline:
            lines.extend([f"> 本章未成稿。大纲：{chapter.outline.strip()}", ""])
        elif options.include_drafts:
            lines.extend(["_本章尚未成稿。_", ""])
        if options.include_reviews:
            lines.extend(_markdown_review_lines(chapter))


def _markdown_project(project: Project, options: ExportOptions) -> str:
    lines: list[str] = [f"# {_single_line(project.title, '未命名作品')}", ""]

    if options.include_metadata:
        if project.genre:
            lines.extend([f"> 题材：{project.genre}", ""])
        if project.premise:
            lines.extend(["## 一句话设定", "", project.premise.strip(), ""])

    if options.include_metadata and project.settings:
        lines.extend(["## 设定", ""])
        for setting in sorted(project.settings, key=lambda s: (s.category, s.key)):
            prefix = f"**{setting.category} / {setting.key}**" if setting.category else f"**{setting.key}**"
            lines.extend([f"- {prefix}：{setting.value.strip() or '（空）'}"])
        lines.append("")

    if options.include_metadata and project.characters:
        lines.extend(["## 角色", ""])
        for character in sorted(project.characters, key=lambda c: c.name):
            profile = character.profile or {}
            lines.extend(
                [
                    f"### {_single_line(character.name, '未命名角色')}",
                    "",
                    f"- 性格：{profile.get('personality', '')}",
                    f"- 动机：{profile.get('motivation', '')}",
                    f"- 关系：{profile.get('relationships', '')}",
                    f"- 弧光：{character.arc}",
                    "",
                ]
            )

    if options.include_metadata and project.foreshadows:
        lines.extend(["## 伏笔与支线", ""])
        for item in sorted(project.foreshadows, key=lambda f: f.created_at):
            lines.extend(
                [
                    f"### {item.title}",
                    "",
                    f"- 类型：{item.kind}",
                    f"- 状态：{item.status}",
                    f"- 引入位置：{item.introduced_at}",
                    f"- 描述：{item.description}",
                    f"- 回收/推进计划：{item.payoff}",
                    "",
                ]
            )

    if options.include_metadata and project.truth_files:
        lines.extend(["## 真相文件", ""])
        for item in sorted(project.truth_files, key=lambda t: t.created_at):
            lines.extend(
                [
                    f"### {_single_line(item.title, '未命名真相')}",
                    "",
                    f"- 类型：{item.kind}",
                    f"- 状态：{item.status}",
                    f"- 范围：{item.scope}",
                    f"- 相关对象：{item.owner}",
                    f"- 内容：{item.content}",
                    "",
                ]
            )

    lines.extend(["## 正文", ""])
    volumes = _novel_volumes(list(project.volumes))
    export_volumes = [volume for volume in volumes if _volume_has_export_content(volume, options)]
    if not export_volumes:
        lines.extend(["_尚未生成大纲。_", ""])

    for volume in export_volumes:
        _append_markdown_volume(lines, volume, options)

    if options.include_references:
        reference_volumes = [volume for volume in _reference_volumes(list(project.volumes)) if _volume_has_export_content(volume, options)]
        if reference_volumes:
            lines.extend(["## 参考资料", ""])
            for volume in reference_volumes:
                _append_markdown_volume(lines, volume, options, reference=True)

    return "\n".join(lines).rstrip() + "\n"


def _outline_context(volumes: list[Volume]) -> str:
    lines: list[str] = []
    for volume in sorted(volumes, key=lambda v: v.order_index):
        lines.append(f"第 {volume.order_index + 1} 卷：{volume.title}。卷纲：{volume.outline}")
        for chapter in sorted(volume.chapters, key=lambda ch: ch.order_index):
            lines.append(f"  第 {chapter.order_index + 1} 章：{chapter.title}。章纲：{chapter.outline}")
    return "\n".join(lines)


def _chapter_context(chapters: list[Chapter]) -> str:
    lines: list[str] = []
    for chapter in sorted(chapters, key=lambda ch: ch.order_index):
        lines.append(f"第 {chapter.order_index + 1} 章：{chapter.title}。章纲：{chapter.outline}")
    return "\n".join(lines)


def _format_truth_files(items: list[TruthFile]) -> str:
    if not items:
        return ""
    kind_labels = {
        "constraint": "硬约束",
        "resource": "资源账本",
        "relationship": "情感弧线",
        "secret": "隐藏真相",
        "timeline": "长期时间线",
    }
    status_labels = {
        "active": "生效中",
        "draft": "草稿",
        "resolved": "已兑现",
        "archived": "归档",
    }
    lines: list[str] = []
    for item in sorted(items, key=lambda truth: (truth.status == "archived", truth.created_at)):
        if item.status == "archived":
            continue
        kind = kind_labels.get(item.kind, item.kind or "真相")
        status = status_labels.get(item.status, item.status or "active")
        parts = [f"[{status}/{kind}] {item.title}：{item.content}"]
        if item.scope:
            parts.append(f"范围={item.scope}")
        if item.owner:
            parts.append(f"相关={item.owner}")
        lines.append("；".join(parts))
    return "\n".join(f"- {line}" for line in lines)


def _premise_with_truth_files(premise: str, truth_files: str) -> str:
    if not truth_files:
        return premise
    return f"{premise or '（未提供）'}\n\n【长篇真相文件 / 不可违背约束】\n{truth_files}"


def _download_filename(title: str, extension: str) -> str:
    safe = _single_line(title, "novel").replace("/", "-").replace("\\", "-")
    return f"{safe}.{extension}"


def _xhtml_text(text: str, empty: str = "") -> str:
    paragraphs = [p.strip() for p in (text or "").replace("\r\n", "\n").split("\n\n") if p.strip()]
    if not paragraphs and empty:
        paragraphs = [empty]
    return "\n".join(
        f"<p>{escape(paragraph).replace(chr(10), '<br />')}</p>" for paragraph in paragraphs
    )


def _xhtml_page(title: str, body: str) -> str:
    return f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <title>{escape(title)}</title>
  <style>
    body {{ font-family: serif; line-height: 1.8; margin: 1.5em; }}
    h1, h2, h3 {{ line-height: 1.35; }}
    blockquote {{ color: #555; margin-left: 0; padding-left: 1em; border-left: 0.2em solid #bbb; }}
  </style>
</head>
<body>
{body}
</body>
</html>
"""


def _front_matter_xhtml(project: Project) -> str:
    parts: list[str] = [f"<h1>{escape(_single_line(project.title, '未命名作品'))}</h1>"]
    if project.genre:
        parts.append(f"<p><strong>题材：</strong>{escape(project.genre)}</p>")
    if project.premise:
        parts.extend(["<h2>一句话设定</h2>", _xhtml_text(project.premise)])
    if project.settings:
        parts.append("<h2>设定</h2><ul>")
        for setting in sorted(project.settings, key=lambda s: (s.category, s.key)):
            label = f"{setting.category} / {setting.key}" if setting.category else setting.key
            parts.append(f"<li><strong>{escape(label)}</strong>：{escape(setting.value or '（空）')}</li>")
        parts.append("</ul>")
    if project.characters:
        parts.append("<h2>角色</h2>")
        for character in sorted(project.characters, key=lambda c: c.name):
            profile = character.profile or {}
            parts.extend(
                [
                    f"<h3>{escape(_single_line(character.name, '未命名角色'))}</h3>",
                    "<ul>",
                    f"<li>性格：{escape(profile.get('personality', ''))}</li>",
                    f"<li>动机：{escape(profile.get('motivation', ''))}</li>",
                    f"<li>关系：{escape(profile.get('relationships', ''))}</li>",
                    f"<li>弧光：{escape(character.arc or '')}</li>",
                    "</ul>",
                ]
            )
    if project.foreshadows:
        parts.append("<h2>伏笔与支线</h2>")
        for item in sorted(project.foreshadows, key=lambda f: f.created_at):
            parts.extend(
                [
                    f"<h3>{escape(_single_line(item.title, '未命名追踪项'))}</h3>",
                    "<ul>",
                    f"<li>类型：{escape(item.kind)}</li>",
                    f"<li>状态：{escape(item.status)}</li>",
                    f"<li>引入位置：{escape(item.introduced_at or '')}</li>",
                    f"<li>描述：{escape(item.description or '')}</li>",
                    f"<li>回收/推进计划：{escape(item.payoff or '')}</li>",
                    "</ul>",
                ]
            )
    if project.truth_files:
        parts.append("<h2>真相文件</h2>")
        for item in sorted(project.truth_files, key=lambda t: t.created_at):
            parts.extend(
                [
                    f"<h3>{escape(_single_line(item.title, '未命名真相'))}</h3>",
                    "<ul>",
                    f"<li>类型：{escape(item.kind)}</li>",
                    f"<li>状态：{escape(item.status)}</li>",
                    f"<li>范围：{escape(item.scope or '')}</li>",
                    f"<li>相关对象：{escape(item.owner or '')}</li>",
                    f"<li>内容：{escape(item.content or '')}</li>",
                    "</ul>",
                ]
            )
    return "\n".join(parts)


def _review_xhtml(chapter: Chapter) -> str:
    review = chapter.latest_review
    if review is None:
        return ""
    parts: list[str] = ["<section><h3>审校报告</h3>"]
    if review.summary:
        parts.append(f"<p><strong>摘要：</strong>{escape(review.summary)}</p>")
    parts.append(f"<p><strong>AI 味评分：</strong>{review.ai_flavor_score}</p>")
    if review.model:
        parts.append(f"<p><strong>模型：</strong>{escape(review.model)}</p>")
    if review.issues:
        parts.append("<ul>")
        for issue in review.issues[:20]:
            if not isinstance(issue, dict):
                continue
            severity = escape(str(issue.get("severity") or "medium"))
            issue_type = escape(str(issue.get("type") or "issue"))
            location = escape(str(issue.get("location") or ""))
            description = escape(str(issue.get("description") or ""))
            suggestion = escape(str(issue.get("suggestion") or ""))
            text = f"[{severity}/{issue_type}]"
            if location:
                text += f" {location}"
            if description:
                text += f"：{description}"
            if suggestion:
                text += f"；建议：{suggestion}"
            parts.append(f"<li>{text}</li>")
        parts.append("</ul>")
    parts.append("</section>")
    return "\n".join(parts)


def _append_epub_volume_pages(
    pages: list[tuple[str, str, str]],
    volume: Volume,
    options: ExportOptions,
    prefix: str,
    reference: bool = False,
) -> None:
    chapters = _export_chapters(volume, options)
    if not chapters and not _volume_has_export_content(volume, options):
        return
    volume_title = (
        f"参考资料 · {_single_line(volume.title, '未命名资料组')}"
        if reference
        else f"第 {volume.order_index + 1} 卷 · {_single_line(volume.title, '未命名卷')}"
    )
    if not chapters:
        href = f"{prefix}/volume-{volume.order_index + 1}.xhtml"
        body = f"<h1>{escape(volume_title)}</h1>" + _xhtml_text(volume.outline, "本卷还没有章节。")
        pages.append((href, volume_title, body))
        return
    for chapter in chapters:
        href = f"{prefix}/chapter-{volume.order_index + 1}-{chapter.order_index + 1}.xhtml"
        chapter_title = (
            f"资料 · {_single_line(chapter.title, '未命名章节')}"
            if reference
            else f"第 {chapter.order_index + 1} 章 · {_single_line(chapter.title, '未命名章节')}"
        )
        content = (chapter.content or "").strip()
        if content:
            chapter_body = _xhtml_text(content)
        elif options.include_drafts and chapter.outline:
            chapter_body = f"<blockquote>{_xhtml_text('本章未成稿。大纲：' + chapter.outline)}</blockquote>"
        elif options.include_drafts:
            chapter_body = _xhtml_text("本章尚未成稿。")
        else:
            continue
        if options.include_reviews:
            chapter_body += "\n" + _review_xhtml(chapter)
        pages.append(
            (
                href,
                f"{volume_title} / {chapter_title}",
                f"<h1>{escape(volume_title)}</h1>\n<h2>{escape(chapter_title)}</h2>\n{chapter_body}",
            )
        )


def _epub_project(project: Project, options: ExportOptions) -> bytes:
    title = _single_line(project.title, "未命名作品")
    modified = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    pages: list[tuple[str, str, str]] = []
    if options.include_metadata:
        pages.append(("front.xhtml", "作品资料", _front_matter_xhtml(project)))

    for volume in _novel_volumes(list(project.volumes)):
        _append_epub_volume_pages(pages, volume, options, prefix="text")

    if options.include_references:
        for volume in _reference_volumes(list(project.volumes)):
            _append_epub_volume_pages(pages, volume, options, prefix="reference", reference=True)

    if not pages:
        pages.append(("front.xhtml", "空导出", _xhtml_text("当前导出选项下没有可导出的内容。")))

    nav_items = "\n".join(
        f'<li><a href="{escape(href)}">{escape(page_title)}</a></li>' for href, page_title, _ in pages
    )
    nav_page = _xhtml_page(
        "目录", f'<nav epub:type="toc" id="toc"><h1>目录</h1><ol>{nav_items}</ol></nav>'
    )
    manifest_items = [
        '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav" />'
    ]
    spine_items: list[str] = []
    xhtml_files: list[tuple[str, str]] = [("nav.xhtml", nav_page)]
    for index, (href, page_title, body) in enumerate(pages, start=1):
        item_id = f"page-{index}"
        manifest_items.append(
            f'<item id="{item_id}" href="{escape(href)}" media-type="application/xhtml+xml" />'
        )
        spine_items.append(f'<itemref idref="{item_id}" />')
        xhtml_files.append((href, _xhtml_page(page_title, body)))

    package_opf = f"""<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="bookid">urn:uuid:{escape(project.id)}</dc:identifier>
    <dc:title>{escape(title)}</dc:title>
    <dc:language>zh-CN</dc:language>
    <meta property="dcterms:modified">{modified}</meta>
  </metadata>
  <manifest>
    {chr(10).join(manifest_items)}
  </manifest>
  <spine>
    {chr(10).join(spine_items)}
  </spine>
</package>
"""
    container_xml = """<?xml version="1.0" encoding="utf-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="EPUB/package.opf" media-type="application/oebps-package+xml" />
  </rootfiles>
</container>
"""
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip", compress_type=ZIP_STORED)
        archive.writestr("META-INF/container.xml", container_xml, compress_type=ZIP_DEFLATED)
        archive.writestr("EPUB/package.opf", package_opf, compress_type=ZIP_DEFLATED)
        for href, page in xhtml_files:
            archive.writestr(f"EPUB/{href}", page, compress_type=ZIP_DEFLATED)
    return buffer.getvalue()


@router.post("", response_model=ProjectOut, status_code=201)
async def create_project(
    body: ProjectCreate, session: AsyncSession = Depends(get_session)
) -> Project:
    project = Project(**body.model_dump())
    session.add(project)
    await session.commit()
    await session.refresh(project)
    return project


@router.get("", response_model=list[ProjectOut])
async def list_projects(session: AsyncSession = Depends(get_session)) -> list[Project]:
    result = await session.execute(select(Project).order_by(Project.created_at.desc()))
    return list(result.scalars().all())


@router.get("/{project_id}", response_model=ProjectDetail)
async def get_project(
    project_id: str, session: AsyncSession = Depends(get_session)
) -> Project:
    return await _get_project_detail_or_404(session, project_id)


@router.put("/{project_id}/model", response_model=ProjectOut)
async def update_project_model(
    project_id: str,
    body: ProjectModelUpdate,
    session: AsyncSession = Depends(get_session),
) -> Project:
    project = await _get_project_or_404(session, project_id)
    style_guide = project.style_guide if isinstance(project.style_guide, dict) else {}
    next_style = {**style_guide}
    model = body.model.strip()
    if model:
        next_style["model"] = model
    else:
        next_style.pop("model", None)
    project.style_guide = next_style
    await session.commit()
    await session.refresh(project)
    return project


@router.put("/{project_id}/continuation-anchor", response_model=ProjectOut)
async def update_project_continuation_anchor(
    project_id: str,
    body: ProjectContinuationAnchorUpdate,
    session: AsyncSession = Depends(get_session),
) -> Project:
    project = await _get_project_or_404(session, project_id)
    style_guide = project.style_guide if isinstance(project.style_guide, dict) else {}
    next_style = {**style_guide}
    if body.chapter_id:
        result = await session.execute(
            select(Chapter, Volume)
            .join(Volume, Chapter.volume_id == Volume.id)
            .where(Chapter.id == body.chapter_id, Volume.project_id == project_id)
        )
        row = result.first()
        if row is None:
            raise HTTPException(status_code=404, detail="续写起点章节不存在")
        chapter, volume = row
        next_style["continuation_anchor"] = {
            "chapter_id": chapter.id,
            "chapter_title": chapter.title,
            "volume_id": volume.id,
            "volume_title": volume.title,
        }
    else:
        next_style.pop("continuation_anchor", None)
    project.style_guide = next_style
    await session.commit()
    await session.refresh(project)
    return project


@router.get("/{project_id}/export")
async def export_project(
    project_id: str,
    format: str = Query("markdown", pattern="^(markdown|md|epub)$"),
    include_metadata: bool = Query(True),
    include_reviews: bool = Query(False),
    include_references: bool = Query(False),
    include_drafts: bool = Query(True),
    session: AsyncSession = Depends(get_session),
) -> Response:
    project = await _get_project_detail_or_404(session, project_id)
    options = ExportOptions(
        include_metadata=include_metadata,
        include_reviews=include_reviews,
        include_references=include_references,
        include_drafts=include_drafts,
    )
    if format == "epub":
        filename = _download_filename(project.title, "epub")
        return Response(
            content=_epub_project(project, options),
            media_type="application/epub+zip",
            headers={
                "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
            },
        )

    filename = _download_filename(project.title, "md")
    return Response(
        content=_markdown_project(project, options),
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
        },
    )


@router.delete("/{project_id}", status_code=204)
async def delete_project(
    project_id: str, session: AsyncSession = Depends(get_session)
) -> None:
    project = await _get_project_or_404(session, project_id)
    await session.delete(project)
    await session.commit()


@router.post("/{project_id}/characters/generate", response_model=list[CharacterOut])
async def generate_project_characters(
    project_id: str,
    body: CharacterGenerateRequest,
    session: AsyncSession = Depends(get_session),
) -> list[Character]:
    project = await _get_project_or_404(session, project_id)
    result = await generate_characters(
        premise=project.premise,
        genre=project.genre,
        count=body.count,
        model=resolve_project_model(project, body.model),
    )
    created: list[Character] = []
    for item in result.characters:
        character = Character(
            project_id=project.id,
            name=item.name,
            profile=item.profile.model_dump(),
            arc=item.arc,
        )
        session.add(character)
        created.append(character)
    await session.commit()
    for c in created:
        await session.refresh(c)
        # 灌入检索片段，让 RAG 一开始就能召回角色设定。
        p = c.profile or {}
        await index_chunk(
            session,
            project_id=project.id,
            source_type="character",
            source_id=c.id,
            text=f"角色 {c.name}：{p.get('personality', '')} 动机:{p.get('motivation', '')} 关系:{p.get('relationships', '')} 弧光:{c.arc}",
            keywords=[c.name],
        )
    await session.commit()
    return created


def _character_chunk_text(c: Character) -> str:
    p = c.profile or {}
    return (
        f"角色 {c.name}：{p.get('personality', '')} 动机:{p.get('motivation', '')} "
        f"关系:{p.get('relationships', '')} 弧光:{c.arc}"
    )


async def _sync_character_chunk(session: AsyncSession, c: Character) -> None:
    chunk_res = await session.execute(
        select(MemoryChunk).where(
            MemoryChunk.source_type == "character",
            MemoryChunk.source_id == c.id,
        )
    )
    chunk = chunk_res.scalar_one_or_none()
    if chunk is None:
        await index_chunk(
            session,
            project_id=c.project_id,
            source_type="character",
            source_id=c.id,
            text=_character_chunk_text(c),
            keywords=[c.name],
        )
    else:
        chunk.text = _character_chunk_text(c)
        chunk.keywords = [c.name]


@router.post("/{project_id}/characters", response_model=CharacterOut, status_code=201)
async def create_project_character(
    project_id: str,
    body: CharacterCreate,
    session: AsyncSession = Depends(get_session),
) -> Character:
    """手动新增角色卡，并同步检索片段。"""
    project = await _get_project_or_404(session, project_id)
    character = Character(
        project_id=project.id,
        name=body.name,
        profile=body.profile or {},
        arc=body.arc,
    )
    session.add(character)
    await session.flush()
    await _sync_character_chunk(session, character)
    await session.commit()
    await session.refresh(character)
    return character


@router.put("/characters/{character_id}", response_model=CharacterOut)
async def update_project_character(
    character_id: str,
    body: CharacterUpdate,
    session: AsyncSession = Depends(get_session),
) -> Character:
    """人工编辑角色卡（名称/档案/弧光），并同步检索片段。"""
    character = await session.get(Character, character_id)
    if character is None:
        raise HTTPException(status_code=404, detail="角色不存在")
    data = body.model_dump(exclude_none=True)
    if "name" in data:
        character.name = data["name"]
    if "arc" in data:
        character.arc = data["arc"]
    if "profile" in data:
        merged = dict(character.profile or {})
        merged.update(data["profile"] or {})
        character.profile = merged
    await _sync_character_chunk(session, character)
    await session.commit()
    await session.refresh(character)
    return character


@router.delete("/characters/{character_id}", status_code=204)
async def delete_project_character(
    character_id: str,
    session: AsyncSession = Depends(get_session),
) -> None:
    """删除角色卡及其检索片段。"""
    character = await session.get(Character, character_id)
    if character is None:
        raise HTTPException(status_code=404, detail="角色不存在")
    chunk_res = await session.execute(
        select(MemoryChunk).where(
            MemoryChunk.source_type == "character",
            MemoryChunk.source_id == character.id,
        )
    )
    for chunk in chunk_res.scalars().all():
        await session.delete(chunk)
    await session.delete(character)
    await session.commit()


@router.put("/chapters/{chapter_id}/outline", response_model=VolumeOut)
async def update_chapter_outline(
    chapter_id: str,
    body: ChapterOutlineUpdate,
    session: AsyncSession = Depends(get_session),
) -> Volume:
    """人工编辑章节标题/大纲（不改正文），返回所属卷的最新结构。"""
    chapter = await session.get(Chapter, chapter_id)
    if chapter is None:
        raise HTTPException(status_code=404, detail="章节不存在")
    data = body.model_dump(exclude_none=True)
    if "title" in data:
        chapter.title = data["title"]
    if "outline" in data:
        chapter.outline = data["outline"]
    await session.commit()
    volume = await session.execute(
        select(Volume)
        .where(Volume.id == chapter.volume_id)
        .options(
            selectinload(Volume.chapters).selectinload(Chapter.reviews),
            selectinload(Volume.chapters).selectinload(Chapter.summary_row),
        )
    )
    return volume.scalar_one()


@router.post("/{project_id}/outline/generate", response_model=list[VolumeOut])
async def generate_project_outline(
    project_id: str,
    body: OutlineGenerateRequest,
    session: AsyncSession = Depends(get_session),
) -> list[Volume]:
    project = await _get_project_detail_or_404(session, project_id)
    style = style_text_from_guide(project.style_guide, "")
    premise = _premise_with_truth_files(project.premise, _format_truth_files(list(project.truth_files)))
    existing_volumes = _novel_volumes(list(project.volumes))
    result = await generate_outline(
        premise=premise,
        genre=project.genre,
        style=style,
        volume_count=body.volume_count,
        chapters_per_volume=body.chapters_per_volume,
        existing_outline=_outline_context(existing_volumes),
        model=resolve_project_model(project, body.model),
    )
    created: list[Volume] = []
    volume_offset = max((v.order_index for v in existing_volumes), default=-1) + 1
    for v_idx, v in enumerate(result.volumes):
        volume = Volume(
            project_id=project.id,
            order_index=volume_offset + v_idx,
            kind="novel",
            title=v.title,
            outline=v.outline,
        )
        for c_idx, ch in enumerate(v.chapters):
            volume.chapters.append(
                Chapter(order_index=c_idx, title=ch.title, outline=ch.outline, status="outlined")
            )
        session.add(volume)
        created.append(volume)
    await session.commit()

    # 灌入卷大纲为检索片段（含项目设定关键词），让 RAG 召回背景。
    for v in created:
        await index_chunk(
            session,
            project_id=project.id,
            source_type="volume_outline",
            source_id=v.id,
            text=f"{v.title}：{v.outline}",
            keywords=[v.title],
        )
    await session.commit()

    # 重新查询以带出 chapters 关系，供响应序列化。
    result_q = await session.execute(
        select(Volume)
        .where(Volume.project_id == project.id)
        .options(selectinload(Volume.chapters).selectinload(Chapter.summary_row))
        .order_by(Volume.order_index)
    )
    return list(result_q.scalars().all())


@router.post("/{project_id}/outline/fill", response_model=list[VolumeOut])
async def fill_project_outline(
    project_id: str,
    body: OutlineFillRequest,
    session: AsyncSession = Depends(get_session),
) -> list[Volume]:
    project = await _get_project_detail_or_404(session, project_id)
    novel_volumes = _novel_volumes(list(project.volumes))
    if not novel_volumes:
        raise HTTPException(status_code=400, detail="项目还没有正文大纲，请先生成大纲")

    style = style_text_from_guide(project.style_guide, "")
    premise = _premise_with_truth_files(project.premise, _format_truth_files(list(project.truth_files)))
    existing_outline = _outline_context(novel_volumes)
    changed = False
    for volume in novel_volumes:
        chapters = sorted(volume.chapters, key=lambda ch: ch.order_index)
        missing_count = body.chapters_per_volume - len(chapters)
        if missing_count <= 0:
            continue
        result = await generate_volume_chapters(
            premise=premise,
            genre=project.genre,
            style=style,
            existing_outline=existing_outline,
            volume_title=volume.title,
            volume_outline=volume.outline,
            existing_chapters=_chapter_context(chapters),
            additional_count=missing_count,
            model=resolve_project_model(project, body.model),
        )
        chapter_offset = max((chapter.order_index for chapter in chapters), default=-1) + 1
        for index, chapter_outline in enumerate(result.chapters):
            volume.chapters.append(
                Chapter(
                    order_index=chapter_offset + index,
                    title=chapter_outline.title,
                    outline=chapter_outline.outline,
                    status="outlined",
                )
            )
        changed = True

    if changed:
        await session.commit()

    result_q = await session.execute(
        select(Volume)
        .where(Volume.project_id == project.id)
        .options(selectinload(Volume.chapters).selectinload(Chapter.summary_row))
        .order_by(Volume.order_index)
    )
    return list(result_q.scalars().all())
