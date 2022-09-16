import matplotlib.pyplot as plt  # vision
from wordcloud import WordCloud, ImageColorGenerator, STOPWORDS  # 词云，颜色生成器，停止词
import numpy as np  #
from PIL import Image
import get_okr_feishu

def ciyun():

    frequencies = get_okr_feishu.get_keys_freq()

    backgroud = np.array(Image.open('okr.png'))

    wc = WordCloud(width=2200, height=1400,
                   background_color='white',
                   mode='RGB',
                   mask=backgroud,  # 添加蒙版，生成指定形状的词云，并且词云图的颜色可从蒙版里提取
                   max_words=500,
                   #stopwords=STOPWORDS.add('Tidb'),  # 内置的屏蔽词,并添加自己设置的词语
                   font_path='simfang.ttf',
                   max_font_size=150,
                   relative_scaling=0.6,  # 设置字体大小与词频的关联程度为0.4
                   random_state=50,
                   scale=2
                   ).generate_from_frequencies(frequencies)

    #image_color = ImageColorGenerator(backgroud)  # 设置生成词云的颜色，如去掉这两行则字体为默认颜色
#    wc.recolor(color_func=image_color)

    plt.imshow(wc)  # 显示词云
    plt.axis('off')  # 关闭x,y轴
    plt.show()  # 显示
    wc.to_file('ciyun.jpg')  # 保存词云图


def main():
    ciyun()


if __name__ == '__main__':
    main()
