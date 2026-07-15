const fs = require('fs');
const path = require('path');
const axios = require('axios');

// 配置文件路径
const CONFIG_FILE = path.join(__dirname, 'config.json');

// 密钥文件路径（ethan .secrets 目录）
const SECRETS_DIR = path.join(
  process.env.HOME || process.env.USERPROFILE || '~',
  '.ethan', '.secrets'
);
const SECRET_KEY_FILE = path.join(SECRETS_DIR, 'amap_webservice_key');

/**
 * 读取配置文件
 */
function readConfig() {
  try {
    if (fs.existsSync(CONFIG_FILE)) {
      const data = fs.readFileSync(CONFIG_FILE, 'utf8');
      return JSON.parse(data);
    }
  } catch (error) {
    // ignore
  }
  return {};
}

/**
 * 从 ~/.ethan/.secrets/amap_webservice_key 读取密钥
 */
function readSecretKey() {
  try {
    if (fs.existsSync(SECRET_KEY_FILE)) {
      return fs.readFileSync(SECRET_KEY_FILE, 'utf8').trim();
    }
  } catch (error) {
    // ignore
  }
  return null;
}

/**
 * 获取高德 Web Service Key
 * 优先级：环境变量 > .secrets 文件 > config.json
 */
async function ensureWebServiceKey() {
  // 1. 环境变量
  let key = process.env.AMAP_WEBSERVICE_KEY || process.env.AMAP_KEY;

  // 2. ~/.ethan/.secrets/amap_webservice_key
  if (!key) {
    key = readSecretKey();
  }

  // 3. 本地 config.json
  if (!key) {
    const config = readConfig();
    key = config.webServiceKey || null;
  }

  if (!key) {
    console.error('\n未找到高德 Web Service Key');
    console.error('请通过 Ethan 设置: set_secret("amap_webservice_key", "你的key")');
    console.error('或设置环境变量: export AMAP_WEBSERVICE_KEY=your_key');
    console.error('获取 Key: https://lbs.amap.com/api/webservice/create-project-and-key\n');
    throw new Error('未配置高德 Web Service Key');
  }

  return key;
}

/**
 * POI 搜索
 */
async function searchPOI(params) {
  const key = await ensureWebServiceKey();

  const url = 'https://restapi.amap.com/v5/place/text';

  const requestParams = {
    ...params,
    key,
    keywords: params.keywords || '',
    region: params.city || '',
    city_limit: params.cityLimit !== false,
  };

  try {
    console.log('正在搜索 POI...');
    const response = await axios.get(url, { params: requestParams });

    if (response.data.status === '1') {
      console.log(`搜索成功，共找到 ${response.data.count} 条结果\n`);
      return response.data;
    } else {
      console.error('搜索失败:', response.data.info);
      return null;
    }
  } catch (error) {
    console.error('请求失败:', error.message);
    return null;
  }
}

/**
 * 步行路径规划
 */
async function walkingRoute(params) {
  const key = await ensureWebServiceKey();

  const url = 'https://restapi.amap.com/v3/direction/walking';

  const requestParams = {
    key: key,
    origin: params.origin,
    destination: params.destination
  };

  try {
    console.log('正在规划步行路线...');
    const response = await axios.get(url, { params: requestParams });

    if (response.data.status === '1') {
      console.log('步行路线规划成功\n');
      return response.data;
    } else {
      console.error('步行路线规划失败:', response.data.info);
      return null;
    }
  } catch (error) {
    console.error('请求失败:', error.message);
    return null;
  }
}

/**
 * 驾车路径规划
 */
async function drivingRoute(params) {
  const key = await ensureWebServiceKey();

  const url = 'https://restapi.amap.com/v3/direction/driving';

  const requestParams = {
    key: key,
    origin: params.origin,
    destination: params.destination,
    strategy: params.strategy || 10,
    extensions: 'base'
  };

  if (params.waypoints) {
    requestParams.waypoints = params.waypoints;
  }

  try {
    console.log('正在规划驾车路线...');
    const response = await axios.get(url, { params: requestParams });

    if (response.data.status === '1') {
      console.log('驾车路线规划成功\n');
      return response.data;
    } else {
      console.error('驾车路线规划失败:', response.data.info);
      return null;
    }
  } catch (error) {
    console.error('请求失败:', error.message);
    return null;
  }
}

/**
 * 骑行路径规划
 */
async function ridingRoute(params) {
  const key = await ensureWebServiceKey();

  const url = 'https://restapi.amap.com/v4/direction/bicycling';

  const requestParams = {
    key: key,
    origin: params.origin,
    destination: params.destination
  };

  try {
    console.log('正在规划骑行路线...');
    const response = await axios.get(url, { params: requestParams });

    if (response.data.errcode === 0) {
      console.log('骑行路线规划成功\n');
      return response.data;
    } else {
      console.error('骑行路线规划失败:', response.data.errmsg);
      return null;
    }
  } catch (error) {
    console.error('请求失败:', error.message);
    return null;
  }
}

/**
 * 公交路径规划
 */
async function transitRoute(params) {
  const key = await ensureWebServiceKey();

  const url = 'https://restapi.amap.com/v3/direction/transit/integrated';

  const requestParams = {
    key: key,
    origin: params.origin,
    destination: params.destination,
    city: params.city,
    strategy: params.strategy || 0,
    nightflag: params.nightflag ? 1 : 0
  };

  try {
    console.log('正在规划公交路线...');
    const response = await axios.get(url, { params: requestParams });

    if (response.data.status === '1') {
      console.log('公交路线规划成功\n');
      return response.data;
    } else {
      console.error('公交路线规划失败:', response.data.info);
      return null;
    }
  } catch (error) {
    console.error('请求失败:', error.message);
    return null;
  }
}

/**
 * 生成地图可视化链接
 */
function generateMapLink(mapTaskData) {
  const baseUrl = 'https://a.amap.com/jsapi_demo_show/static/openclaw/travel_plan.html';
  const dataStr = encodeURIComponent(JSON.stringify(mapTaskData));
  return `${baseUrl}?data=${dataStr}`;
}

/**
 * 旅游规划助手
 */
async function travelPlanner(params) {
  const { city, interests = [], routeType = 'walking' } = params;

  console.log(`\n开始为您规划 ${city} 的旅游行程...\n`);

  const mapTaskData = [];
  const poiResults = [];

  // 搜索各类兴趣点
  for (const interest of interests) {
    console.log(`搜索 ${interest}...`);
    const result = await searchPOI({
      keywords: interest,
      city: city,
      page: 1,
      offset: 5
    });

    if (result && result.pois && result.pois.length > 0) {
      poiResults.push(...result.pois);

      result.pois.forEach(poi => {
        if (!poi.location) return;
        const [lng, lat] = poi.location.split(',').map(Number);
        if (isNaN(lng) || isNaN(lat)) return;
        mapTaskData.push({
          type: 'poi',
          lnglat: [lng, lat],
          sort: poi.type || interest,
          text: poi.name,
          remark: poi.address || `${interest}推荐`
        });
      });
    }
  }

  // 如果有多个POI，规划路线
  if (poiResults.length >= 2) {
    console.log(`\n规划游览路线（${routeType}）...\n`);

    for (let i = 0; i < poiResults.length - 1; i++) {
      const start = poiResults[i];
      const end = poiResults[i + 1];

      const [startLng, startLat] = start.location.split(',').map(Number);
      const [endLng, endLat] = end.location.split(',').map(Number);

      const routeTask = {
        type: 'route',
        routeType: routeType,
        start: [startLng, startLat],
        end: [endLng, endLat],
        remark: `从 ${start.name} 到 ${end.name}`
      };

      if (routeType === 'transfer') {
        routeTask.city = city;
      }

      mapTaskData.push(routeTask);
    }
  }

  console.log('\n旅游规划完成！\n');
  console.log('推荐地点：');
  poiResults.forEach((poi, index) => {
    console.log(`${index + 1}. ${poi.name}`);
    console.log(`   地址: ${poi.address}`);
    console.log(`   类型: ${poi.type}\n`);
  });

  return {
    pois: poiResults,
    mapTaskData: mapTaskData,
  };
}

// 导出函数供其他脚本使用
module.exports = {
  readConfig,
  readSecretKey,
  ensureWebServiceKey,
  searchPOI,
  walkingRoute,
  drivingRoute,
  ridingRoute,
  transitRoute,
  generateMapLink,
  travelPlanner
};

// 如果直接运行此文件，执行示例搜索
if (require.main === module) {
  (async () => {
    try {
      const result = await searchPOI({
        keywords: '肯德基',
        city: '北京',
        page: 1,
        offset: 10
      });

      if (result && result.pois) {
        console.log('搜索结果:');
        result.pois.forEach((poi, index) => {
          console.log(`${index + 1}. ${poi.name}`);
          console.log(`   地址: ${poi.address}`);
          console.log(`   类型: ${poi.type}`);
          console.log(`   坐标: ${poi.location}\n`);
        });
      }
    } catch (error) {
      console.error('执行失败:', error.message);
      process.exit(1);
    }
  })();
}
