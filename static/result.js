let lang = window.navigator.language;

tt.getUserInfo({
     // getUserInfo API 调用成功回调
     success(res) {
           console.log(`getUserInfo success: ${JSON.stringify(res)}`);
           // 单独定义的函数showUser，用于将用户信息展示在前端页面上
           showUser(res.userInfo)
     },
     // getUserInfo API 调用失败回调
     fail(err) {
          console.log(`getUserInfo failed, err:`, JSON.stringify(err));
     }
})

unction showUser(res) {
    // 展示用户信息
    // 头像
    $('#img_div').html(`<img src="${res.avatarUrl}" width="100%" height=""100%/>`)
    // 名称
    $('#hello_text_name').text(lang === "zh_CN" || lang === "zh-CN" ? `${res.nickName}` : `${res.i18nName.en_us}`);
    // 欢迎语
    $('#hello_text_welcome').text(lang === "zh_CN" || lang === "zh-CN" ? "欢迎使用飞书" : "welcome to Feishu");
}

