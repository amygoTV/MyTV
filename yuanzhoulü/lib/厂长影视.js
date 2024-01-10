var rule={
    title:'厂长资源',
    //host:'https://www.cz01.vip',
    host:'https://www.czzy33.com',
    //hostJs:'print(HOST);let html=request(HOST,{headers:{"User-Agent":PC_UA}});HOST = jsp.pdfh(html,"h3&&a&&href")',
    url:'/fyclass/page/fypage',
    filterable:0,//是否启用分类筛选,
    searchUrl:'/xssearch?q=**',
    searchable:1,
    filterable:1,
    headers:{
        'User-Agent': 'MOBILE_UA',
        'Cookie': 'myannoun=1; cf_clearance=pojWu9MPhNCLWJpt35N7zfRu1GfACpPftdc3HWahGoc-1701080379-0-1-ef25ee04.1c8c2efc.85ab8473-150.0.0'
    },
    class_name:'豆瓣电影top250&电影&美剧&韩剧&动漫',
    class_url:'dbtop250&movie_bt_series/dyy&meijutt&hanjutv&dm',
	play_parse:true,
    lazy:`js:
        pdfh = jsp.pdfh;
        var html = request(input);
        var ohtml = pdfh(html, '.videoplay&&Html');
        var url = pdfh(ohtml, "body&&iframe&&src");
        if (/Cloud/.test(url)) {
            var ifrwy = request(url);
            let code = ifrwy.match(/var url = '(.*?)'/)[1].split('').reverse().join('');
            let temp = '';
            for (let i = 0x0; i < code.length; i = i + 0x2) {
                temp += String.fromCharCode(parseInt(code[i] + code[i + 0x1], 0x10))
            }
            input = {
                jx: 0,
                url: temp.substring(0x0, (temp.length - 0x7) / 0x2) + temp.substring((temp.length - 0x7) / 0x2 + 0x7),
                parse: 0
            }
        } else if (/decrypted/.test(ohtml)) {
            var phtml = pdfh(ohtml, "body&&script:not([src])&&Html");
            eval(getCryptoJS());
            var scrpt = phtml.match(/var.*?\\)\\);/g)[0];
            var data = [];
            eval(scrpt.replace(/md5/g, 'CryptoJS').replace('eval', 'data = '));
            input = {
                jx: 0,
                url: data.match(/url:.*?[\\'\\"](.*?)[\\'\\"]/)[1],
                parse: 0
            }
        } else {
            input
        }
	`,
    推荐:'.bt_img;ul&&li;*;*;*;*',
    double:true,
    一级:'.bt_img&&ul&&li;h3.dytit&&Text;img.lazy&&data-original;.hdinfo&&Text;a&&href',
    二级:{
        "title": "h1&&Text;.moviedteail_list li&&a&&Text",
        "img": "div.dyimg img&&src",
        "desc": ".moviedteail_list li:eq(10) a&&Text;.moviedteail_list li:eq(2) a&&Text;.moviedteail_list li:eq(1) a&&Text;.moviedteail_list li:eq(7)&&Text;.moviedteail_list li:eq(5)&&Text",
        "content": ".yp_context&&Text",
        "tabs": ".mi_paly_box span",
        "lists": ".paly_list_btn:eq(#id) a"
    },
    搜索:'.search_list&&ul&&li;*;*;*;*',
    // 预处理:'rule_fetch_params.headers.Cookie="68148872828e9f4d64e7a296f6c6b6d7=5429da9a54375db451f7f9e4f16ce0ea;esc_search_captcha=1";let new_host="https://czspp.com";let new_html=request(new_host);if(/正在进行人机识别/.test(new_html)){let new_src=pd(new_html,"script&&src",new_host);log(new_src);let hhtml=request(new_src,{withHeaders:true});let json=JSON.parse(hhtml);let html=json.body;let key=html.match(new RegExp(\'var key="(.*?)"\'))[1];let avalue=html.match(new RegExp(\'value="(.*?)"\'))[1];let c="";for(let i=0;i<avalue.length;i++){let a=avalue[i];let b=a.charCodeAt();c+=b}let value=md5(c);log(value);let yz_url="https://czspp.com/a20be899_96a6_40b2_88ba_32f1f75f1552_yanzheng_ip.php?type=96c4e20a0e951f471d32dae103e83881&key="+key+"&value="+value;log(yz_url);hhtml=request(yz_url,{withHeaders:true});json=JSON.parse(hhtml);let setCk=Object.keys(json).find(it=>it.toLowerCase()==="set-cookie");let cookie=setCk?json[setCk].split(";")[0]:"";log("cookie:"+cookie);rule_fetch_params.headers.Cookie=cookie;setItem(RULE_CK,cookie)}',
}
