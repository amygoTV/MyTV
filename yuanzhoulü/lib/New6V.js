var rule = {
	title:'New6V',
	host:'http://www.xb6v.com',
	// url: '/fyclass/index_(fypage-1).html',
	url: '/fyclassfyfilter/index_fypage.html[/fyclassfyfilter/index.html]',
	searchUrl: '/e/search/index.php#show=title&tempid=1&tbname=article&mid=1&dopost=search&submit=&keyboard=**;post',
	filter_url:'{{fl.class}}',
	filter:{
		"dianshiju":[{"key":"class","name":"类型","value":[{"n":"全部","v":""},{"n":"国剧","v":"/guoju"},{"n":"日韩剧","v":"/rihanju"},{"n":"欧美剧","v":"/oumeiju"}]}]
	},
	searchable:1,
	quickSearch:1,
	filterable:0,
	headers:{
		'User-Agent': 'MOBILE_UA'
	},
	timeout:10000,
	class_parse:'#menus&&li:gt(1);a&&Text;a&&href;.*/(.*)/',
	cate_exclude:'旧版6v|国剧|日韩剧|欧美剧',
	play_parse:true,
	lazy:'',
	limit:12,
	推荐: '*',
	一级: '#post_container&&li;h2&&Text;img&&src;.info_category&&Text;a&&href',
	/*一级: `js:
		pdfh=jsp.pdfh;pdfa=jsp.pdfa;pd=jsp.pd;
		var d = [];
		var html = request(input);
		var list = pdfa(html, 'body&&.post_hover');
		list.forEach(it => {
			d.push({
				title: pdfh(it, 'h2&&Text'),
				desc: pdfh(it, '.info_category&&Text'),
				pic_url: pdfh(it, 'img&&src'),
				url: pd(it, 'a&&href')
			});
		})
		setResult(d);
	`,*/
	二级:{
		title:'.h1&&Text;.info_category&&Text',
		img:'.mainleft p:eq(0)&&src',
		content:'.context p:eq(2)&&Text',
		tabs: `js:
			TABS = ["磁力播放[观影后,记得清理缓存]"];
			let tabs = pdfa(html, '#content&&h3:not(:contains(网盘))');
			tabs.forEach((it) => {
				TABS.push(pdfh(it, "body&&Text").replace('播放地址','在线播放').replace('（无插件 极速播放）','一').replace('（无需安装插件）','二'))
			});
		`,
		lists: `js:
			log(TABS);
			pdfh=jsp.pdfh;pdfa=jsp.pdfa;pd=jsp.pd;
			LISTS = [];
			let i = 1;
			TABS.forEach(function(tab) {
				if (/磁力播放/.test(tab)) {
					var d = pdfa(html, '.context&&td');
					d = d.map(function(it) {
						var title = pdfh(it, 'a&&Text');
						var burl = pd(it, 'a&&href');
						return title + '$' + burl
					});
					LISTS.push(d)
				} else if (/在线播放/.test(tab) && i <= TABS.length-1) {
					var d = pdfa(html, '.context&&.widget:eq(list_idx)&&a'.replace("list_idx", i));
					d = d.map(function(it) {
						var title = pdfh(it, 'a&&Text');
						var burl = pd(it, 'a&&href');
						return title + '$' + burl
					});
					LISTS.push(d)
					i = i + 1;
				}
			});
		`,
	},
	搜索: '*',
}