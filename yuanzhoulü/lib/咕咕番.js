var rule = {
     title: '咕咕番',
     host: 'https://www.gugufan.com',
     searchUrl: '/index.php/vod/search/wd/**.html',
     url: '/index.php/vod/show/id/fyclass.html',
     searchable: 2,//是否启用全局搜索,
     quickSearch: 1,//是否启用快速搜索,
     filterable: 0,//是否启用分类筛选,
     headers: {
       'User-Agent': 'MOBILE_UA'
     },
     play_parse: true,
     lazy: '',
     limit: 6,
     推荐: '*',
     double: true, // 推荐内容是否双层定位
     一级: '.public-list-exp;a&&title;img&&data-src;.ft2&&Text;a&&href',
     二级: {
         "title": "h1&&Text;.hl-ma0&&Text",
         "img": ".module-item-pic&&img&&data-src",
         "desc": ".slide-info-remarks&&Text;.video-info-items:eq(2)&&Text;.video-infs&&Text;.video-info-item:eq(1)&&Text;.video-info-items:eq(0)&&Text",
          "content": "#height_limit&&Text",
          "tabs": ".anthology-tab&&a",
          "lists": ".anthology-list-box:eq(#id)&&li"
     },
     搜索: '.public-list-box;.thumb-txt&&Text;.public-list-exp&&img&&data-src;.public-list-prb&&Text;a&&href'
    }