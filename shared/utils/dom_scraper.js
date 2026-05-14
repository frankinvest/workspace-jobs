/**
 * shared/utils/dom_scraper.js
 *
 * 通用正文 + 图片联合提取器（DFS 深度优先遍历）
 *
 * 核心思想：
 *   不分离提取"纯文本"和"图片列表"，而是将两者融合在同一条文本流中。
 *   遍历 DOM 树，遇到文本节点 → 追加文本；遇到 <img> → 追加 `![img](src)\n`
 *   输出格式：Markdown 风格的图文混排字符串，无穷节点扁平化。
 *
 * 使用方式：
 *   const mixedContent = DomScraper.extractMixedContent('article', { maxLength: 100000 });
 *   // mixedContent = "正文文字![img](https://private.site/xxx?token=...)正文..."
 *
 * 渲染模块收到后：
 *   1. 用正则提取所有 `![img](url)` 中的 URL 列表
 *   2. 批量上传到 GitHub
 *   3. URL 替换为 GitHub Raw URL
 *   4. 将 `![img](url)` 替换为 `<img src="url">`
 */

(function(global) {
  'use strict';

  var DomScraper = {
    /**
     * 主入口：提取正文 + 图片的混合文本
     * @param {string} rootSelector - 正文容器选择器（CSS selector）
     * @param {Object} options - 可选配置
     * @param {number} options.maxLength - 最大返回长度（防止 evaluate 超限）
     * @param {string[]} options.skipClasses - 跳过含有这些 class 名的元素
     * @returns {string} 混排文本（含 `![img](url)` 标记）
     */
    extractMixedContent: function(rootSelector, options) {
      options = options || {};
      var maxLength = options.maxLength || 50000;
      var skipClasses = options.skipClasses || ['comment', 'reply', 'footer', 'sidebar', 'ad'];

      var root = typeof rootSelector === 'string'
        ? document.querySelector(rootSelector)
        : rootSelector;

      if (!root) {
        console.error('[DomScraper] 未找到根元素:', rootSelector);
        return '';
      }

      var result = [];
      var self = this;

      function dfs(node) {
        if (result.join('').length > maxLength) return;

        if (node.nodeType === Node.TEXT_NODE) {
          // 纯文本节点：追加文本内容（trim 避免多余空白）
          var text = node.textContent.replace(/[\r\n]+/g, ' ').trim();
          if (text.length > 0) {
            result.push(text + '\n');
          }
          return;
        }

        if (node.nodeType !== Node.ELEMENT_NODE) return;

        var el = node;

        // 跳过评论区等非正文区域
        if (skipClasses && self._hasAnyClass(el, skipClasses)) {
          return;
        }

        var tagName = el.tagName ? el.tagName.toLowerCase() : '';

        // 图片元素：提取 src
        if (tagName === 'img') {
          var src = el.src || el.getAttribute('data-src') || '';
          // 过滤 avatar 和 tiny 图标
          if (src && !self._isSkipImage(src)) {
            result.push('\n![img](' + src + ')\n');
          }
          return;
        }

        // 特殊行内元素：追加换行保持结构
        var inlineTags = {'br': true, 'p': true, 'div': true, 'h1': true, 'h2': true, 'h3': true,
                          'h4': true, 'h5': true, 'h6': true, 'li': true, 'tr': true};

        // 分割线等装饰性元素
        if (tagName === 'hr' || (el.textContent || '').match(/^[-*_]{5,}$/)) {
          result.push('\n---\n');
          return;
        }

        // 遍历子节点
        var child = el.firstChild;
        while (child) {
          dfs(child);
          child = child.nextSibling;
        }

        // 块级元素结束后追加换行
        if (inlineTags[tagName]) {
          result.push('\n');
        }
      }

      dfs(root);

      var output = result.join('').substring(0, maxLength);
      return output;
    },

    /**
     * 提取评论列表（保持原有 comment_builder 逻辑不变）
     * @param {string} selector - 评论容器选择器
     * @returns {Array} 评论列表
     */
    extractComments: function(selector) {
      selector = selector || '.comment-list, .comments, [class*="comment"]';
      var container = typeof selector === 'string'
        ? document.querySelector(selector)
        : selector;

      if (!container) return [];

      var items = container.querySelectorAll('.item, .comment-item, [class*="cmt-item"]');
      var comments = [];

      for (var i = 0; i < items.length; i++) {
        var el = items[i];
        var text = el.textContent || '';
        var tm = text.match(/(\d{2}:\d{2})/);
        if (!tm) continue;

        var time = tm[1];
        var idx = text.indexOf(time);
        var before = text.substring(0, idx - 1);
        var dm = before.match(/(\S{2,20})(\d{2}\/\d{2}|今天)\s*$/);
        if (!dm) continue;

        comments.push({
          user: dm[1].trim(),
          time: dm[2] + ' ' + time,
          content: text.substring(idx + time.length)
            .replace(/^[\n\r]*/, '')
            .replace(/查看图片/g, '')
            .trim()
        });
      }
      return comments;
    },

    // ---- 私有辅助方法 ----

    _hasAnyClass: function(el, classes) {
      if (!el || !el.className) return false;
      var cls = el.className.baseVal !== undefined
        ? el.className.baseVal
        : String(el.className || '');
      for (var i = 0; i < classes.length; i++) {
        var re = new RegExp('(^|\\s)' + classes[i] + '(\\s|$)');
        if (re.test(cls)) return true;
      }
      return false;
    },

    _isSkipImage: function(src) {
      var skipPatterns = [
        'avatar', 'icon', 'logo', 'avatar', 'userhead',
        'data:image', 'base64,', 'placeholder', '/0x0'
      ];
      for (var i = 0; i < skipPatterns.length; i++) {
        if (src.indexOf(skipPatterns[i]) !== -1) return true;
      }
      return false;
    }
  };

  // 导出到全局
  global.DomScraper = DomScraper;

})(typeof window !== 'undefined' ? window : global);
