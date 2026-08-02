"""parse_items 方法单元测试"""

import pytest

from src.services.scanner import ScanService


@pytest.fixture
def service():
    """创建 ScanService 实例"""
    return ScanService()


class TestParseItemsWebdavContainer:
    """测试 #webdav-list 容器识别"""

    def test_no_webdav_list_container(self, service):
        """测试没有 #webdav-list 容器时返回空列表"""
        html = """
        <ul>
            <li style="margin:8px 0;"><a href="?dir=folder1">folder1</a></li>
        </ul>
        """
        items = service.parse_items(html)
        assert len(items) == 0

    def test_webdav_list_empty(self, service):
        """测试 #webdav-list 容器为空"""
        html = '<div id="webdav-list"></div>'
        items = service.parse_items(html)
        assert len(items) == 0

    def test_li_without_margin_style(self, service):
        """测试没有 margin style 的 li 被忽略"""
        html = """
        <div id="webdav-list">
            <li><a href="?dir=folder1">folder1</a></li>
            <li style="margin:8px 0;"><a href="?dir=folder2">folder2</a></li>
        </div>
        """
        items = service.parse_items(html)
        assert len(items) == 1
        assert items[0] == ("dir", "folder2", "?dir=folder2")

    def test_nested_webdav_list(self, service):
        """测试嵌套的 #webdav-list 会包含所有 li 元素"""
        html = """
        <div id="webdav-list">
            <li style="margin:8px 0;"><a href="?dir=folder1">folder1</a></li>
            <div id="webdav-list">
                <li style="margin:8px 0;"><a href="file1.txt">file1.txt</a></li>
            </div>
        </div>
        """
        items = service.parse_items(html)
        assert len(items) == 2
        assert items[0] == ("dir", "folder1", "?dir=folder1")
        assert items[1] == ("file", "file1.txt", "file1.txt")

    def test_multiple_webdav_lists(self, service):
        """测试多个 #webdav-list 只取第一个"""
        html = """
        <div id="webdav-list">
            <li style="margin:8px 0;"><a href="?dir=folder1">folder1</a></li>
        </div>
        <div id="webdav-list">
            <li style="margin:8px 0;"><a href="file1.txt">file1.txt</a></li>
        </div>
        """
        items = service.parse_items(html)
        assert len(items) == 1
        assert items[0] == ("dir", "folder1", "?dir=folder1")


class TestParseItemsBasic:
    """测试基本解析功能"""

    def test_dir_with_href(self, service):
        """测试带 dir= href 的目录"""
        html = """
        <div id="webdav-list">
            <li style="margin:8px 0;"><a href="?dir=folder1">folder1</a></li>
        </div>
        """
        items = service.parse_items(html)
        assert len(items) == 1
        assert items[0] == ("dir", "folder1", "?dir=folder1")

    def test_file_without_dir_href(self, service):
        """测试不带 dir= href 的文件"""
        html = """
        <div id="webdav-list">
            <li style="margin:8px 0;"><a href="file1.txt">file1.txt</a></li>
        </div>
        """
        items = service.parse_items(html)
        assert len(items) == 1
        assert items[0] == ("file", "file1.txt", "file1.txt")

    def test_mixed_items(self, service):
        """测试混合目录和文件"""
        html = """
        <div id="webdav-list">
            <li style="margin:8px 0;"><a href="?dir=folder1">folder1</a></li>
            <li style="margin:8px 0;"><a href="file1.txt">file1.txt</a></li>
            <li style="margin:8px 0;"><a href="?dir=folder2">folder2</a></li>
        </div>
        """
        items = service.parse_items(html)
        assert len(items) == 3
        assert items[0] == ("dir", "folder1", "?dir=folder1")
        assert items[1] == ("file", "file1.txt", "file1.txt")
        assert items[2] == ("dir", "folder2", "?dir=folder2")

    def test_emoji_prefix_removed(self, service):
        """测试 Emoji 前缀被正确移除"""
        html = """
        <div id="webdav-list">
            <li style="margin:8px 0;"><a href="?dir=folder1">📁 folder1</a></li>
            <li style="margin:8px 0;"><a href="file1.txt">📄 file1.txt</a></li>
            <li style="margin:8px 0;"><a href="?dir=folder2">📁 folder2</a></li>
        </div>
        """
        items = service.parse_items(html)
        assert len(items) == 3
        assert items[0] == ("dir", "folder1", "?dir=folder1")
        assert items[1] == ("file", "file1.txt", "file1.txt")
        assert items[2] == ("dir", "folder2", "?dir=folder2")

    def test_emoji_prefix_with_chinese(self, service):
        """测试中文名称的 Emoji 前缀移除"""
        html = """
        <div id="webdav-list">
            <li style="margin:8px 0;"><a href="?dir=audio/3000">📁 3000</a></li>
            <li style="margin:8px 0;"><a href="?dir=audio/陈奕迅">📁 陈奕迅</a></li>
            <li style="margin:8px 0;"><a href="audio/song.mp3">📄 song.mp3</a></li>
        </div>
        """
        items = service.parse_items(html)
        assert len(items) == 3
        assert items[0] == ("dir", "3000", "?dir=audio/3000")
        assert items[1] == ("dir", "陈奕迅", "?dir=audio/陈奕迅")
        assert items[2] == ("file", "song.mp3", "audio/song.mp3")


class TestParseItemsFiltering:
    """测试过滤条件"""

    def test_skip_empty_href(self, service):
        """测试跳过空 href"""
        html = """
        <div id="webdav-list">
            <li style="margin:8px 0;"><a href="">folder1</a></li>
            <li style="margin:8px 0;"><a href="#">folder2</a></li>
        </div>
        """
        items = service.parse_items(html)
        assert len(items) == 0

    def test_skip_hash_href(self, service):
        """测试跳过 # href"""
        html = """
        <div id="webdav-list">
            <li style="margin:8px 0;"><a href="#">folder1</a></li>
        </div>
        """
        items = service.parse_items(html)
        assert len(items) == 0

    def test_skip_back_link(self, service):
        """测试跳过返回上级链接"""
        html = """
        <div id="webdav-list">
            <li style="margin:8px 0;"><a href="?dir=..">返回上级</a></li>
        </div>
        """
        items = service.parse_items(html)
        assert len(items) == 0


class TestParseItemsEdgeCases:
    """测试边界情况"""

    def test_empty_html(self, service):
        """测试空 HTML"""
        html = ""
        items = service.parse_items(html)
        assert len(items) == 0

    def test_no_li_elements(self, service):
        """测试没有 li 元素"""
        html = '<div id="webdav-list"></div>'
        items = service.parse_items(html)
        assert len(items) == 0

    def test_li_without_a(self, service):
        """测试 li 没有 a 元素"""
        html = """
        <div id="webdav-list">
            <li style="margin:8px 0;">text without link</li>
        </div>
        """
        items = service.parse_items(html)
        assert len(items) == 0

    def test_multiple_ul(self, service):
        """测试多个 ul 元素"""
        html = """
        <div id="webdav-list">
            <ul>
                <li style="margin:8px 0;"><a href="?dir=folder1">folder1</a></li>
            </ul>
            <ul>
                <li style="margin:8px 0;"><a href="file1.txt">file1.txt</a></li>
            </ul>
        </div>
        """
        items = service.parse_items(html)
        assert len(items) == 2
        assert items[0] == ("dir", "folder1", "?dir=folder1")
        assert items[1] == ("file", "file1.txt", "file1.txt")

    def test_nested_li(self, service):
        """测试嵌套 li 元素"""
        html = """
        <div id="webdav-list">
            <li style="margin:8px 0;">
                <a href="?dir=folder1">folder1</a>
                <ul>
                    <li style="margin:8px 0;"><a href="file1.txt">file1.txt</a></li>
                </ul>
            </li>
        </div>
        """
        items = service.parse_items(html)
        assert len(items) == 2
        assert items[0] == ("dir", "folder1", "?dir=folder1")
        assert items[1] == ("file", "file1.txt", "file1.txt")


class TestParseItemsDirectoryStructure:
    """测试目录结构解析"""

    def test_subdirectories(self, service):
        """测试子目录"""
        html = """
        <div id="webdav-list">
            <li style="margin:8px 0;"><a href="?dir=audio/3000">3000</a></li>
            <li style="margin:8px 0;"><a href="?dir=audio/陈奕迅">陈奕迅</a></li>
            <li style="margin:8px 0;"><a href="?dir=audio/周杰伦">周杰伦</a></li>
        </div>
        """
        items = service.parse_items(html)
        assert len(items) == 3
        assert items[0] == ("dir", "3000", "?dir=audio/3000")
        assert items[1] == ("dir", "陈奕迅", "?dir=audio/陈奕迅")
        assert items[2] == ("dir", "周杰伦", "?dir=audio/周杰伦")

    def test_files_in_directory(self, service):
        """测试目录中的文件"""
        html = """
        <div id="webdav-list">
            <li style="margin:8px 0;"><a href="audio/song1.mp3">song1.mp3</a></li>
            <li style="margin:8px 0;"><a href="audio/song2.flac">song2.flac</a></li>
        </div>
        """
        items = service.parse_items(html)
        assert len(items) == 2
        assert items[0] == ("file", "song1.mp3", "audio/song1.mp3")
        assert items[1] == ("file", "song2.flac", "audio/song2.flac")

    def test_mixed_content(self, service):
        """测试混合内容的目录"""
        html = """
        <div id="webdav-list">
            <li style="margin:8px 0;"><a href="?dir=audio/3000">3000</a></li>
            <li style="margin:8px 0;"><a href="audio/song1.mp3">song1.mp3</a></li>
            <li style="margin:8px 0;"><a href="?dir=audio/陈奕迅">陈奕迅</a></li>
            <li style="margin:8px 0;"><a href="audio/song2.flac">song2.flac</a></li>
        </div>
        """
        items = service.parse_items(html)
        assert len(items) == 4
        assert items[0] == ("dir", "3000", "?dir=audio/3000")
        assert items[1] == ("file", "song1.mp3", "audio/song1.mp3")
        assert items[2] == ("dir", "陈奕迅", "?dir=audio/陈奕迅")
        assert items[3] == ("file", "song2.flac", "audio/song2.flac")


class TestParseItemsFileFormats:
    """测试各种文件格式"""

    def test_video_formats(self, service):
        """测试视频格式"""
        html = """
        <div id="webdav-list">
            <li style="margin:8px 0;"><a href="video/movie.mp4">movie.mp4</a></li>
            <li style="margin:8px 0;"><a href="video/clip.avi">clip.avi</a></li>
            <li style="margin:8px 0;"><a href="video/film.mkv">film.mkv</a></li>
            <li style="margin:8px 0;"><a href="video/record.mov">record.mov</a></li>
        </div>
        """
        items = service.parse_items(html)
        assert len(items) == 4
        assert items[0] == ("file", "movie.mp4", "video/movie.mp4")
        assert items[1] == ("file", "clip.avi", "video/clip.avi")
        assert items[2] == ("file", "film.mkv", "video/film.mkv")
        assert items[3] == ("file", "record.mov", "video/record.mov")

    def test_audio_formats(self, service):
        """测试音频格式"""
        html = """
        <div id="webdav-list">
            <li style="margin:8px 0;"><a href="audio/song.mp3">song.mp3</a></li>
            <li style="margin:8px 0;"><a href="audio/music.flac">music.flac</a></li>
            <li style="margin:8px 0;"><a href="audio/voice.wav">voice.wav</a></li>
            <li style="margin:8px 0;"><a href="audio/tone.aac">tone.aac</a></li>
        </div>
        """
        items = service.parse_items(html)
        assert len(items) == 4
        assert items[0] == ("file", "song.mp3", "audio/song.mp3")
        assert items[1] == ("file", "music.flac", "audio/music.flac")
        assert items[2] == ("file", "voice.wav", "audio/voice.wav")
        assert items[3] == ("file", "tone.aac", "audio/tone.aac")

    def test_archive_formats(self, service):
        """测试压缩包格式"""
        html = """
        <div id="webdav-list">
            <li style="margin:8px 0;"><a href="archive/data.zip">data.zip</a></li>
            <li style="margin:8px 0;"><a href="archive/files.rar">files.rar</a></li>
            <li style="margin:8px 0;"><a href="archive/backup.7z">backup.7z</a></li>
            <li style="margin:8px 0;"><a href="archive/package.tar.gz">package.tar.gz</a></li>
        </div>
        """
        items = service.parse_items(html)
        assert len(items) == 4
        assert items[0] == ("file", "data.zip", "archive/data.zip")
        assert items[1] == ("file", "files.rar", "archive/files.rar")
        assert items[2] == ("file", "backup.7z", "archive/backup.7z")
        assert items[3] == ("file", "package.tar.gz", "archive/package.tar.gz")

    def test_document_formats(self, service):
        """测试文档格式"""
        html = """
        <div id="webdav-list">
            <li style="margin:8px 0;"><a href="docs/report.pdf">report.pdf</a></li>
            <li style="margin:8px 0;"><a href="docs/letter.docx">letter.docx</a></li>
            <li style="margin:8px 0;"><a href="docs/budget.xlsx">budget.xlsx</a></li>
            <li style="margin:8px 0;"><a href="docs/slides.pptx">slides.pptx</a></li>
        </div>
        """
        items = service.parse_items(html)
        assert len(items) == 4
        assert items[0] == ("file", "report.pdf", "docs/report.pdf")
        assert items[1] == ("file", "letter.docx", "docs/letter.docx")
        assert items[2] == ("file", "budget.xlsx", "docs/budget.xlsx")
        assert items[3] == ("file", "slides.pptx", "docs/slides.pptx")

    def test_image_formats(self, service):
        """测试图片格式"""
        html = """
        <div id="webdav-list">
            <li style="margin:8px 0;"><a href="photos/pic.jpg">pic.jpg</a></li>
            <li style="margin:8px 0;"><a href="photos/image.png">image.png</a></li>
            <li style="margin:8px 0;"><a href="photos/anim.gif">anim.gif</a></li>
            <li style="margin:8px 0;"><a href="photos/vector.svg">vector.svg</a></li>
        </div>
        """
        items = service.parse_items(html)
        assert len(items) == 4
        assert items[0] == ("file", "pic.jpg", "photos/pic.jpg")
        assert items[1] == ("file", "image.png", "photos/image.png")
        assert items[2] == ("file", "anim.gif", "photos/anim.gif")
        assert items[3] == ("file", "vector.svg", "photos/vector.svg")


class TestParseItemsDataUrl:
    """测试 data-url / data-filename 格式（新版服务器格式）"""

    def test_data_url_with_hash_href(self, service):
        """测试 href="#" + data-url 格式的文件"""
        html = """
        <div id="webdav-list">
            <li style="margin:8px 0;">
                <a class="webdav-video-link"
                   data-filename="%5B%E8%8C%B9%E4%BC%8A%E6%98%A0%E7%94%BB-Ryyh.net%5D%23%E6%B1%9F%E5%8D%97%E7%AC%AC%E4%B8%80%E6%B7%B1%E6%83%85_Video.0265.MOV"
                   data-url="/webdav/%E7%A6%8F%E5%88%A9/test/%5B%E8%8C%B9%E4%BC%8A%E6%98%A0%E7%94%BB-Ryyh.net%5D%23%E6%B1%9F%E5%8D%97%E7%AC%AC%E4%B8%80%E6%B7%B1%E6%83%85_Video.0265.MOV"
                   href="#">? [茹伊映画-Ryyh.net]#江南第一深情_Video.0265.MOV</a>
            </li>
        </div>
        """
        items = service.parse_items(html)
        assert len(items) == 1
        assert items[0][0] == "file"
        # 文件名应从 data-filename 解码，而不是从文本内容获取
        assert items[0][1] == "[茹伊映画-Ryyh.net]#江南第一深情_Video.0265.MOV"
        # href 应使用 data-url
        assert (
            items[0][2]
            == "/webdav/%E7%A6%8F%E5%88%A9/test/%5B%E8%8C%B9%E4%BC%8A%E6%98%A0%E7%94%BB-Ryyh.net%5D%23%E6%B1%9F%E5%8D%97%E7%AC%AC%E4%B8%80%E6%B7%B1%E6%83%85_Video.0265.MOV"
        )

    def test_data_url_multiple_files(self, service):
        """测试多个 data-url 格式的文件"""
        html = """
        <div id="webdav-list">
            <li style="margin:8px 0;">
                <a class="webdav-video-link"
                   data-filename="video1.MOV"
                   data-url="/webdav/video1.MOV"
                   href="#">? video1.MOV</a>
            </li>
            <li style="margin:8px 0;">
                <a class="webdav-video-link"
                   data-filename="video2.MOV"
                   data-url="/webdav/video2.MOV"
                   href="#">? video2.MOV</a>
            </li>
        </div>
        """
        items = service.parse_items(html)
        assert len(items) == 2
        assert items[0] == ("file", "video1.MOV", "/webdav/video1.MOV")
        assert items[1] == ("file", "video2.MOV", "/webdav/video2.MOV")

    def test_data_url_with_normal_href(self, service):
        """测试同时有 data-url 和正常 href 时，使用原始 href"""
        html = """
        <div id="webdav-list">
            <li style="margin:8px 0;">
                <a href="old_url.txt"
                   data-url="/webdav/new_url.txt"
                   data-filename="new_url.txt">file.txt</a>
            </li>
        </div>
        """
        items = service.parse_items(html)
        assert len(items) == 1
        # 当 href 有真实值时，使用原始 href
        assert items[0] == ("file", "new_url.txt", "old_url.txt")

    def test_data_url_empty_href_treated_as_file(self, service):
        """测试空 href + data-url 格式"""
        html = """
        <div id="webdav-list">
            <li style="margin:8px 0;">
                <a href=""
                   data-url="/webdav/file.txt"
                   data-filename="file.txt">file.txt</a>
            </li>
        </div>
        """
        items = service.parse_items(html)
        assert len(items) == 1
        assert items[0] == ("file", "file.txt", "/webdav/file.txt")

    def test_data_url_dir_detection(self, service):
        """测试 data-url 格式的目录"""
        html = """
        <div id="webdav-list">
            <li style="margin:8px 0;">
                <a href="#"
                   data-url="?dir=subfolder">subfolder</a>
            </li>
        </div>
        """
        items = service.parse_items(html)
        assert len(items) == 1
        assert items[0] == ("dir", "subfolder", "?dir=subfolder")


class TestParseItemsPlusDecoding:
    """修复回归:目录/文件名中的 + 被错误解码为空格

    服务器显示文本把 "+" 渲染成空格（如 "flac MP3"），而 href 中 dir 参数
    是双重编码的真实路径（如 "flac%2BMP3"）。解析器应从 href 解码名称，
    避免缓存名称与真实路径不一致导致刷新时 404。
    """

    def test_dir_plus_decoded_from_href(self, service):
        """目录名含 + 时从 href 解码,不采用显示文本的空格版"""
        html = """
        <div id="webdav-list">
            <li style="margin:8px 0;">
                <a href="?dir=audio%2FC%25E9%2599%2588%25E5%25A5%2595%25E8%25BF%2585%25E6%25AD%258C%25E6%259B%25B2%25E5%2590%2588%25E9%259B%2586%25E3%2580%2590flac%2BMP3%25E5%258F%258C%25E6%25A0%25BC%25E5%25BC%258F%25E3%2580%2591">
                C陈奕迅歌曲合集【flac MP3双格式】
                </a>
            </li>
        </div>
        """
        items = service.parse_items(html)
        assert len(items) == 1
        # 显示文本是空格版,应从 href 解码出 + 版
        assert items[0][1] == "C陈奕迅歌曲合集【flac+MP3双格式】"

    def test_dir_plain_name_kept(self, service):
        """普通目录名(无 +)保持与显示文本一致"""
        html = """
        <div id="webdav-list">
            <li style="margin:8px 0;"><a href="?dir=folder1">folder1</a></li>
        </div>
        """
        items = service.parse_items(html)
        assert items[0] == ("dir", "folder1", "?dir=folder1")

    def test_file_plus_decoded_from_url(self, service):
        """文件名含 + 时从 URL 最后一段解码"""
        html = """
        <div id="webdav-list">
            <li style="margin:8px 0;">
                <a href="https://example.com/audio/%E9%82%93%E7%B4%AB%E6%A3%8B%5BWAV+CUE%5D.flac">
                邓紫棋[WAV CUE].flac
                </a>
            </li>
        </div>
        """
        items = service.parse_items(html)
        assert len(items) == 1
        assert items[0][0] == "file"
        assert items[0][1] == "邓紫棋[WAV+CUE].flac"

    def test_file_plain_name_kept(self, service):
        """普通文件名(无 +)保持与显示文本一致"""
        html = """
        <div id="webdav-list">
            <li style="margin:8px 0;"><a href="/webdav/song.flac">song.flac</a></li>
        </div>
        """
        items = service.parse_items(html)
        assert items[0] == ("file", "song.flac", "/webdav/song.flac")

    def test_dir_with_data_filename_prefers_data_filename(self, service):
        """data-filename 存在时优先使用它,不从 href 解码"""
        html = """
        <div id="webdav-list">
            <li style="margin:8px 0;">
                <a href="?dir=some%2Fpath"
                   data-filename="%E9%99%88%E5%A5%95%E8%BF%85.txt">显示文本</a>
            </li>
        </div>
        """
        items = service.parse_items(html)
        assert len(items) == 1
        assert items[0][1] == "陈奕迅.txt"
