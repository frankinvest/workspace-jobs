#!/usr/bin/env node
/**
 * 市场数据更新脚本 - 使用 Wind 金融数据
 * 
 * 用法:
 *   node scripts/wind-market-update.cjs
 *   node scripts/wind-market-update.cjs --refresh  # 强制刷新
 * 
 * 输出：public/data/market_data.json
 */

const fs = require('fs');
const path = require('path');

// Wind API 配置
const WIND_API_ENABLED = process.env.WIND_API_ENABLED === 'true';
const WIND_API_KEY = process.env.WIND_API_KEY || '';

console.log('🔧 环境配置:');
console.log(`   - Wind API: ${WIND_API_ENABLED ? '已启用' : '禁用 (使用示例数据)'}`);
console.log(`   - API Key: ${WIND_API_KEY ? '已配置' : '未配置'}`);
console.log('');

/**
 * 从 Wind 获取实时行情数据
 */
async function fetchWindRealtimeData() {
  if (!WIND_API_ENABLED) {
    console.log('⚠️  Wind API 未启用，使用示例数据');
    return getExampleData();
  }

  try {
    console.log('📡 连接 Wind API...');
    
    // 调用 Wind 金融数据工具
    const result = await fetch('https://wind-api.internal/v1/query', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${WIND_API_KEY}`,
      },
      body: JSON.stringify({
        queries: [
          'A 股大盘指数实时行情 上证指数 深证成指 创业板指 科创 50',
          '美股指数 纳斯达克 道琼斯 标普 500 日经 225 恒生指数',
          '期货行情 富时 A50 纳指期货 标普期指 原油 黄金',
          '个股行情 贵州茅台 平安银行 招商银行 中国平安 五粮液'
        ]
      })
    });

    if (!result.ok) {
      throw new Error(`Wind API 请求失败：${result.status}`);
    }

    const data = await result.json();
    console.log('✅ Wind API 数据获取成功');
    return data;
  } catch (error) {
    console.warn('⚠️  Wind API 调用失败:', error.message);
    console.log('🔄 降级使用示例数据');
    return getExampleData();
  }
}

/**
 * 获取示例数据（用于测试/演示）
 */
function getExampleData() {
  const now = new Date();
  
  return {
    // A 股大盘指数
    indices: [
      { name: '上证指数', code: 'SH000001', price: 3088.23, change: 7.45, change_pct: 0.24, high: 3095.50, low: 3075.80 },
      { name: '深证成指', code: 'SZ399001', price: 9727.03, change: -25.32, change_pct: -0.26, high: 9780.45, low: 9695.20 },
      { name: '创业板指', code: 'SZ399006', price: 1935.76, change: 8.92, change_pct: 0.46, high: 1945.30, low: 1920.15 },
      { name: '科创 50', code: 'SH000688', price: 768.45, change: 1.85, change_pct: 0.24, high: 772.80, low: 762.30 },
    ],
    
    // 外盘指数
    usIndices: [
      { name: '纳斯达克', code: 'IXIC', price: 20928.97, change: -18.97, change_pct: -0.09, high: 21045.50, low: 20890.25 },
      { name: '道琼斯', code: 'DJI', price: 45452.58, change: 283.80, change_pct: 0.63, high: 45580.30, low: 45210.75 },
      { name: '标普 500', code: 'SPX', price: 5892.44, change: 15.22, change_pct: 0.26, high: 5910.80, low: 5870.15 },
      { name: '日经 225', code: 'N225', price: 38915.87, change: 120.50, change_pct: 0.31, high: 39050.25, low: 38750.40 },
      { name: '恒生指数', code: 'HSI', price: 24951.88, change: -325.60, change_pct: -1.29, high: 25380.50, low: 24890.20 },
    ],
    
    // 期货
    futures: [
      { name: '富时 A50', code: 'XIN9', price: 12845.50, change: 85.20, change_pct: 0.67, high: 12890.75, low: 12750.30 },
      { name: '纳指期指', code: 'NQ', price: 22485.75, change: 95.25, change_pct: 0.43, high: 22550.00, low: 22380.50 },
      { name: '标普期指', code: 'ES', price: 5905.25, change: 18.75, change_pct: 0.32, high: 5920.50, low: 5880.75 },
      { name: '布伦特原油', code: 'BZ', price: 107.16, change: 2.45, change_pct: 2.34, high: 108.50, low: 104.20 },
      { name: '纽约黄金', code: 'GC', price: 2895.40, change: -12.60, change_pct: -0.43, high: 2920.80, low: 2880.15 },
    ],
    
    // 热门个股
    stocks: [
      { name: '贵州茅台', code: 'SH600519', price: 1385.50, change: 8.50, change_pct: 0.62, high: 1395.80, low: 1375.20 },
      { name: '平安银行', code: 'SZ000001', price: 11.02, change: 0.05, change_pct: 0.46, high: 11.15, low: 10.95 },
      { name: '招商银行', code: 'SH600036', price: 33.85, change: -0.25, change_pct: -0.73, high: 34.20, low: 33.60 },
      { name: '中国平安', code: 'SH601318', price: 46.78, change: 0.68, change_pct: 1.48, high: 47.10, low: 46.20 },
      { name: '五粮液', code: 'SZ000858', price: 138.25, change: -1.45, change_pct: -1.04, high: 140.50, low: 137.80 },
    ],
    
    updateTime: now.toLocaleString('zh-CN', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false
    }).replace(/\//g, '-')
  };
}

/**
 * 数据验证和清洗
 */
function validateAndCleanData(data) {
  const cleaned = {
    indices: [],
    usIndices: [],
    futures: [],
    stocks: [],
    updateTime: data.updateTime
  };

  // 验证并清理数组数据
  ['indices', 'usIndices', 'futures', 'stocks'].forEach(key => {
    if (Array.isArray(data[key])) {
      cleaned[key] = data[key].filter(item => {
        if (!item.name || !item.code || !item.price) {
          console.warn(`⚠️  跳过无效数据项: ${item.name || item.code}`);
          return false;
        }
        // 确保数值类型正确
        item.price = Math.round(item.price * 100) / 100;
        item.change = Math.round(item.change * 100) / 100;
        item.change_pct = Math.round(item.change_pct * 100) / 100;
        return true;
      });
    }
  });

  return cleaned;
}

/**
 * 主函数
 */
async function main() {
  try {
    console.log('🚀 开始获取 Wind 市场数据...\n');
    
    // 获取数据
    const rawData = await fetchWindRealtimeData();
    
    // 验证和清洗数据
    const data = validateAndCleanData(rawData);
    
    // 确保输出目录存在
    const outputDir = path.join(__dirname, '..', 'public', 'data');
    if (!fs.existsSync(outputDir)) {
      fs.mkdirSync(outputDir, { recursive: true });
      console.log('📁 创建数据目录:', outputDir);
    }
    
    // 写入 JSON 文件
    const outputPath = path.join(outputDir, 'market_data.json');
    fs.writeFileSync(outputPath, JSON.stringify(data, null, 2), 'utf-8');
    console.log('✅ 市场数据已保存:', outputPath);
    
    // 同步到 dist 目录
    const distOutputPath = path.join(__dirname, '..', 'dist', 'data', 'market_data.json');
    const distDir = path.dirname(distOutputPath);
    if (!fs.existsSync(distDir)) {
      fs.mkdirSync(distDir, { recursive: true });
    }
    fs.writeFileSync(distOutputPath, JSON.stringify(data, null, 2), 'utf-8');
    console.log('✅ 数据已同步到 dist:', distOutputPath);
    
    // 打印统计信息
    console.log('\n📊 数据概览:');
    console.log(`   - A 股指数：${data.indices.length}个`);
    console.log(`   - 外盘指数：${data.usIndices.length}个`);
    console.log(`   - 期货：${data.futures.length}个`);
    console.log(`   - 个股：${data.stocks.length}个`);
    console.log(`   - 总数据项：${data.indices.length + data.usIndices.length + data.futures.length + data.stocks.length}个`);
    console.log(`   - 更新时间：${data.updateTime}`);
    
    // 显示涨跌情况
    const gainers = [
      ...data.indices.filter(i => i.change_pct > 0),
      ...data.usIndices.filter(i => i.change_pct > 0),
      ...data.futures.filter(i => i.change_pct > 0),
      ...data.stocks.filter(i => i.change_pct > 0)
    ];
    const losers = [
      ...data.indices.filter(i => i.change_pct < 0),
      ...data.usIndices.filter(i => i.change_pct < 0),
      ...data.futures.filter(i => i.change_pct < 0),
      ...data.stocks.filter(i => i.change_pct < 0)
    ];
    
    console.log('\n📈 涨跌统计:');
    console.log(`   - 上涨：${gainers.length}个`);
    console.log(`   - 下跌：${losers.length}个`);
    
    if (gainers.length > 0 || losers.length > 0) {
      console.log('\n🏆 涨幅榜 (前 3):');
      [...gainers, ...losers].sort((a, b) => b.change_pct - a.change_pct)
        .slice(0, 3)
        .forEach((item, i) => {
          console.log(`   ${i+1}. ${item.name}: ${item.change_pct > 0 ? '+' : ''}${item.change_pct.toFixed(2)}%`);
        });
    }
    
    console.log('\n✅ 数据更新完成!');
    
  } catch (error) {
    console.error('❌ 更新失败:', error.message);
    console.error(error.stack);
    process.exit(1);
  }
}

main();
