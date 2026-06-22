export function cropperImageByRect(
  imgUrl,
  targetRect,
  srcRect,
  // drawRectOnImage = false /*是否画框到源位置*/,
) {
  // const scale = 2.5;
  return new Promise((resolve, reject) => {
    if (!imgUrl) {
      resolve(null);
      return;
    }
    const img = new Image();

    img.setAttribute('crossOrigin', 'anonymous');
    img.onload = () => {
      const canvas = document.createElement('canvas');
      const targetRatio = targetRect.width / targetRect.height;
      const srcRatio = srcRect.width / srcRect.height;
      const imgRectFit = {};

      if (srcRatio > targetRatio) {
        imgRectFit.width = Math.max(targetRect.width, srcRect.width);
        imgRectFit.height = imgRectFit.width / targetRatio;
      } else {
        imgRectFit.height = Math.max(targetRect.height, srcRect.height);
        imgRectFit.width = imgRectFit.height * targetRatio;
      }

      // 修正过大的问题
      if (imgRectFit.width > img.width && imgRectFit.height > img.height) {
        imgRectFit.height = img.height;
        imgRectFit.width = imgRectFit.width = imgRectFit.height * targetRatio;
      }

      canvas.width = imgRectFit.width;
      canvas.height = imgRectFit.height;

      imgRectFit.left = Math.max(srcRect.x - (imgRectFit.width - srcRect.width) / 2, 0); // 处理左边界溢出
      imgRectFit.top = Math.max(srcRect.y - (imgRectFit.height - srcRect.height) / 2, 0); // 处理上边界溢出

      // 处理右边界溢出
      if (imgRectFit.left + imgRectFit.width > img.width) {
        imgRectFit.left = Math.max(
          imgRectFit.left - (imgRectFit.left + imgRectFit.width - img.width),
          0,
        );
      }
      // 处理下边界溢出
      if (imgRectFit.top + imgRectFit.height > img.height) {
        imgRectFit.top = Math.max(
          imgRectFit.top - (imgRectFit.top + imgRectFit.height - img.height),
          0,
        );
      }

      const ctx = canvas.getContext('2d');
      ctx.drawImage(
        img,
        imgRectFit.left,
        imgRectFit.top,
        imgRectFit.width + 2, // +1 避免图片上的框被截掉
        imgRectFit.height + 2,
        0,
        0,
        canvas.width,
        canvas.height,
      );

      ctx.beginPath();
      ctx.lineWidth = '1';
      ctx.strokeStyle = 'red';
      ctx.rect(
        srcRect.x - imgRectFit.left,
        srcRect.y - imgRectFit.top,
        srcRect.width,
        srcRect.height,
      );
      ctx.stroke();
      resolve(canvas.toDataURL('image/jpeg', 1));
    };

    img.onerror = () => {
      reject(new Error('图片加载失败'));
    };
    img.src = imgUrl;
  });
}

/*
* 图片画框
* imgUrl：原始图片地址
  targetRect：想要截成图片的大小(可选)
  srcRect：绘制框的大小
  InBoxs 置信度数组
*/
export function drawRectOnImage(imageUrl, srcRect, InBoxs) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.setAttribute('crossOrigin', 'anonymous');
    img.onload = () => {
      const canvas = document.createElement('canvas');
      canvas.width = img.width;
      canvas.height = img.height;
      const ctx = canvas.getContext('2d');
      ctx.drawImage(img, 0, 0, img.width, img.height);
      ctx.beginPath();
      ctx.lineWidth = '2';
      ctx.strokeStyle = 'red';
      ctx.font = '15px Arial'; // 设置字体和字号
      ctx.fillStyle = 'red'; // 设置字体颜色
      srcRect.map((item, index) => {
        ctx.rect(item.x, item.y, item.width, item.height);
        ctx.fillText(InBoxs[index].confidence.toFixed(4), item.x, item.y - 5);
      });
      ctx.stroke();
      resolve(canvas.toDataURL('image/jpeg', 1));
    };
    img.onerror = () => {
      reject(new Error('图片加载失败'));
    };
    img.src = imageUrl;
  });
}
