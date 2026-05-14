(function() {
  /* === shared/utils/dom_scraper.js 内容 === */
  var DomScraper = {
    extractMixedContent: function(rootSelector, options) {
      options = options || {};
      var maxLength = options.maxLength || 50000;
      var skipClasses = options.skipClasses || ['comment', 'reply', 'footer', 'sidebar', 'ad'];

      var root = typeof rootSelector === 'string'
        ? document.querySelector(rootSelector)
        : rootSelector;
      if (!root) return '';

      var result = [];
      var self = this;

      function dfs(node) {
        if (result.join('').length > maxLength) return;
        if (node.nodeType === Node.TEXT_NODE) {
          var text = node.textContent.replace(/[\r\n]+/g, ' ').trim();
          if (text.length > 0) result.push(text + '\n');
          return;
        }
        if (node.nodeType !== Node.ELEMENT_NODE) return;
        var el = node;
        if (skipClasses && self._hasAnyClass(el, skipClasses)) return;
        var tagName = el.tagName ? el.tagName.toLowerCase() : '';
        if (tagName === 'img') {
          var src = el.src || el.getAttribute('data-src') || '';
          if (src && !self._isSkipImage(src)) {
            result.push('\n![img](' + src + ')\n');
          }
          return;
        }
        var inlineTags = {'br':true,'p':true,'div':true,'h1':true,'h2':true,'h3':true,'h4':true,'h5':true,'h6':true,'li':true,'tr':true};
        if (tagName === 'hr' || (el.textContent || '').match(/^[-*_]{5,}$/)) {
          result.push('\n---\n');
          return;
        }
        var child = el.firstChild;
        while (child) {
          dfs(child);
          child = child.nextSibling;
        }
        if (inlineTags[tagName]) result.push('\n');
      }

      dfs(root);
      return result.join('').substring(0, maxLength);
    },
    _hasAnyClass: function(el, classes) {
      if (!el || !el.className) return false;
      var cls = el.className.baseVal !== undefined ? el.className.baseVal : String(el.className || '');
      for (var i = 0; i < classes.length; i++) {
        var re = new RegExp('(^|\\s)' + classes[i] + '(\\s|$)');
        if (re.test(cls)) return true;
      }
      return false;
    },
    _isSkipImage: function(src) {
      var skipPatterns = ['avatar','icon','logo','data:image','base64,','placeholder','/0x0'];
      for (var i = 0; i < skipPatterns.length; i++) {
        if (src.indexOf(skipPatterns[i]) !== -1) return true;
      }
      return false;
    }
  };

  /* === 执行提取 === */
  // 找到正文容器（main 或 article）
  var main = document.querySelector('main') || document.querySelector('article') || document.querySelector('.post-content') || document.body;
  
  // 跳过评论区（评论区通常有 'comment' class）
  var contentEl = main.cloneNode(true);
  var comments = contentEl.querySelectorAll('[class*="comment"], [class*="reply"], .cmt-item, .py-12');
  comments.forEach(function(el) { el.remove(); });
  
  // 执行提取
  var mixed = DomScraper.extractMixedContent(contentEl, { maxLength: 40000 });
  
  return mixed;
})()
