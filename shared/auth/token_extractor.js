/**
 * shared/auth/token_extractor.js
 * 
 * 浏览器端通用 Token 提取器
 * 提取 document.cookie 和 localStorage，组成完整的会话凭证
 * 
 * 使用方式（在 Browser Evaluate 中执行）:
 *   const session = extractSessionToken();
 *   // session = { cookies: "...", localStorage: {...}, userAgent: "..." }
 */

(function(global) {
  'use strict';

  /**
   * 提取完整会话凭证
   * @returns {Object} { cookies, localStorage, userAgent }
   */
  function extractSessionToken() {
    var cookieStr = document.cookie || '';
    
    var localStorageData = {};
    try {
      for (var k in localStorage) {
        if (localStorage.hasOwnProperty(k)) {
          try {
            localStorageData[k] = localStorage.getItem(k);
          } catch (e) {
            // 某些 key 可能访问受限，跳过
          }
        }
      }
    } catch (e) {
      console.error('[TokenExtractor] localStorage 访问失败:', e.message);
    }
    
    return {
      cookies: cookieStr,
      localStorage: localStorageData,
      userAgent: navigator.userAgent || '',
      extractedAt: new Date().toISOString()
    };
  }

  /**
   * 等待 localStorage 中出现特定 key（等待扫码登录完成）
   * @param {string|string[]} keys - 要等待的 key 或 key 数组
   * @param {number} intervalMs - 轮询间隔（毫秒）
   * @param {number} timeoutMs - 超时时间（毫秒）
   * @returns {Promise<Object>} 包含 key 和 value 的对象
   */
  function waitForLocalStorageKey(keys, intervalMs, timeoutMs) {
    keys = Array.isArray(keys) ? keys : [keys];
    var startTime = Date.now();
    
    return new Promise(function(resolve, reject) {
      function check() {
        for (var i = 0; i < keys.length; i++) {
          try {
            var val = localStorage.getItem(keys[i]);
            if (val !== null) {
              var result = {};
              result[keys[i]] = val;
              resolve(result);
              return;
            }
          } catch (e) {}
        }
        
        if (Date.now() - startTime >= timeoutMs) {
          reject(new Error('等待 localStorage key 超时: ' + keys.join(', ')));
          return;
        }
        
        setTimeout(check, intervalMs);
      }
      
      check();
    });
  }

  /**
   * 验证会话是否仍然有效（通过访问受保护资源）
   * @param {string[]} protectedUrls - 受保护资源的 URL 列表
   * @returns {Promise<boolean>}
   */
  async function validateSession(protectedUrls) {
    for (var i = 0; i < protectedUrls.length; i++) {
      try {
        var resp = await fetch(protectedUrls[i], {
          method: 'HEAD',
          credentials: 'include'
        });
        if (resp.ok) return true;
      } catch (e) {}
    }
    return false;
  }

  /**
   * 清除会话（退出登录）
   */
  function clearSession() {
    // 清除 cookies
    document.cookie.split(';').forEach(function(c) {
      var parts = c.trim().split('=');
      if (parts.length > 0) {
        document.cookie = parts[0] + '=;expires=Thu, 01 Jan 1970 00:00:00 GMT;path=/';
      }
    });
    
    // 清除 localStorage
    try {
      localStorage.clear();
    } catch (e) {
      console.error('[TokenExtractor] localStorage 清除失败:', e.message);
    }
  }

  // 导出到全局
  global.TokenExtractor = {
    extractSessionToken: extractSessionToken,
    waitForLocalStorageKey: waitForLocalStorageKey,
    validateSession: validateSession,
    clearSession: clearSession
  };

})(typeof window !== 'undefined' ? window : global);
