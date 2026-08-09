#include <stdio.h>
#include <sys/socket.h>
#include <linux/if_alg.h>
#include <string.h>
#include <errno.h>
#include <stdlib.h>
#include <unistd.h>
 
/*
要与内核加密API交互，用户空间应用程序必须创建一个套接字socket。用户空间使用send/write系统调用族调用密码操作。密码运算的结果是通过read/recv系统调用获得的。
*/
 
#ifndef AF_ALG
#define AF_ALG 38
#endif
 
#ifndef SOL_ALG
#define SOL_ALG 279
#endif
 
/* 配置是否使用efuse中的密钥 */
#define SET_KEY_EFUSE 1
/* 选择接收的系统调用接口 0-recvmsg 1-read 2-recv */
#define RECV 1
 
extern int errno;
 
void print(char* src, int len) {
 
    int i;
    for (i = 0; i < len; i++) {
        printf("%x", (unsigned char)src[i]);
    }
    putchar('\n');
}
 
 
int setkey(int fd, char* key, int keylen) {
    /*
    调用应用程序必须使用ALG_SET_KEY的setsockopt()选项。
    如果没有设置该键，则执行HMAC操作时不会因该键导致初始HMAC状态改变。
    */
    int err = setsockopt(fd, SOL_ALG, ALG_SET_KEY, key, keylen);
    if (err) {
        perror("setkey err");
        return -1;
    }
    return 0;
}
 
int sendmsg_to_crypto(int opfd, int cmsg_type, __u32 cmsg_data, char* plaintext_buf, int buflen) {
    /* 描述发送的消息 */
    struct msghdr msg = {};
    //struct cmsghdr *cmsg = malloc(CMSG_SPACE(sizeof(cmsg_data)));
    struct cmsghdr* cmsg = NULL;
    char buff[CMSG_SPACE(sizeof(cmsg_data))] = { 0 };
    /*
        struct iovec 结构体定义了一个向量元素
        通常这个 iovec 结构体用于一个多元素的数组，对于每一个元素，iovec 结构体的字段 iov_base 指向一个缓冲区，
        这个缓冲区存放的是网络接收的数据（read），或者网络将要发送的数据（write）。
        iovec 结构体的字段 iov_len 存放的是接收数据的最大长度（read），或者实际写入的数据长度（write）。
    */
    struct iovec iov;
    int err;
 
    /* 配置了socket的消息结构体 */
    msg.msg_iov = &iov;
    msg.msg_iovlen = 1;
    msg.msg_control = buff;
    msg.msg_controllen = sizeof(buff);
 
    /* 初始化控制消息的实例 */
    cmsg = CMSG_FIRSTHDR(&msg);
 
    cmsg->cmsg_level = SOL_ALG;
    cmsg->cmsg_type = cmsg_type;
    cmsg->cmsg_len = CMSG_SPACE(sizeof(cmsg_data));
    /*
        传输控制消息的data
        使用下列标志之一的密码操作类型的规范:
        ALG_OP_ENCRYPT 数据加密
        ALG_OP_DECRYPT 数据的解密
        IV信息的规范，标记为ALG_SET_IV标志
    */
    //memcpy(CMSG_DATA(cmsg), &cmsg_data, sizeof(cmsg_data));
    *(__u32*)CMSG_DATA(cmsg) = cmsg_data;
 
    /* 配置iov */
    iov.iov_base = plaintext_buf;
    iov.iov_len = buflen;
 
    /* 发送数据 */
    err = sendmsg(opfd, &msg, MSG_MORE);
    if (err == -1) {
        perror("sendmsg err");
        return -1;
    }
    return err;
}
 
int recvmsg_from_crypto(int opfd, char* src, int len) {
    /* 初始化消息结构体和iov结构体用以接收数据 */
    struct msghdr msg = {};
    struct iovec iov;
    int err;
    msg.msg_iov = &iov;
    msg.msg_iovlen = 1;
    iov.iov_base = src;
    iov.iov_len = len;
 
    /* 接收数据 */
    err = recvmsg(opfd, &msg, 0);
    if (err == -1) {
        perror("recvmsg err");
        return -1;
    }
    /* 打印出接收到的加密后的数据 */
    printf("recvmsg_from_crypto hex: ");
    print(src, len);
    return err;
}

char* text_align16(const char* src, long int* len) {
    /* 对字符串进行16字节对齐不足补\0，用于处理AES加密的16字节分组 */
    char* new_str;
    long int new_len = ((*len) / 16 + 1) * 16;
    new_str = malloc((*len) % 16 == 0 ? *len : new_len);
    if (new_str == NULL) {
        perror("text_align16 malloc err");
        exit(EXIT_FAILURE);
    }
    memcpy(new_str, src, *len);
    if ((*len) % 16 == 0)
        return new_str;
    memset(new_str + *len, 0, new_len - *len);
    *len = new_len;
    return new_str;
}
 
int main(int argc, char** argv) {
    /* 使用带有-secure-key后缀的算法名可以让spacc使用efuse中的密钥 */
    struct sockaddr_alg sa = {
        .salg_family = AF_ALG,
        .salg_type = "skcipher",
#if SET_KEY_EFUSE == 1
        .salg_name = "cbc(aes-secure-key)",
#else  
        .salg_name = "cbc(aes)",
#endif
    };
    //char key_buf[16] = { 0xff, 0xd7, 0x40, 0x57, 0x47, 0x68, 0x5e, 0xd6, 0xe0, 0x0b, 0xc6, 0x82, 0xa7, 0x72, 0x86, 0x09 };
    char key_buf[16] = { 0 };
    char* encrypt_buf;
    char* decrypt_buf;
    char* plaintext_buf;
    long int plaintext_buf_len;
    int tfmfd;
    int opfd = -1;
    int opfd2 = -1;
    int err;
    /* 实例需要加密的明文数据 */
    if (argc > 1)
        plaintext_buf = argv[1];
    else
        plaintext_buf = "Single block msgSingle block msg";
    plaintext_buf_len = strlen(plaintext_buf);
    /* 根据输入进行内存空间的申请，确保可以处理超大字符串 */
    encrypt_buf = malloc(plaintext_buf_len + 16);
    /* calloc 清零保证解密输出为 NUL 终止，避免 %s/strlen 越界读 */
    decrypt_buf = calloc(plaintext_buf_len + 16, 1);
    plaintext_buf = text_align16(plaintext_buf, &plaintext_buf_len);
    printf("src text: %s len: %ld->%ld\n", plaintext_buf, strlen(plaintext_buf), plaintext_buf_len);
    /* 申请socket控制句柄 */
    tfmfd = socket(AF_ALG, SOCK_SEQPACKET, 0);
    err = bind(tfmfd, (struct sockaddr*)&sa, sizeof(sa));
    if (err) {
        perror("bind err");
        goto bind_err;
    }
 
    err = setkey(tfmfd, key_buf, sizeof(key_buf));
    if (err) {
        goto setkey_err;
    }
 
    /* 申请一个句柄，用于加密 */
    opfd = accept(tfmfd, NULL, 0);
    if (opfd == -1) {
        perror("accept err");
        goto accept_err;
    }
 
    /* 申请一个句柄，用于解密 */
    opfd2 = accept(tfmfd, NULL, 0);
    if (opfd2 == -1) {
        perror("accept err");
        goto accept_err;
    }
 
    /* 发送数据用以加密 */
    err = sendmsg_to_crypto(opfd, ALG_SET_OP, ALG_OP_ENCRYPT, plaintext_buf, plaintext_buf_len);
    if (err == -1) {
        goto sendmsg_err;
    }
 
    /* 接收加密后的数据 */
    /*
    使用recv()系统调用，应用程序可以从内核加密API读取加密操作的结果。
    输出缓冲区必须至少与保存加密或解密数据的所有块一样大。如果输出数据大小较小，则只返回符合输出缓冲区大小的块。
    */
    err = recvmsg_from_crypto(opfd, encrypt_buf, plaintext_buf_len);
    if (err == -1) {
        goto recv_err;
    }
 
    /* 发送数据用以解密 */
    err = sendmsg_to_crypto(opfd2, ALG_SET_OP, ALG_OP_DECRYPT, encrypt_buf, plaintext_buf_len);
    if (err == -1) {
        goto sendmsg_err;
    }
#if RECV==0
    /* 接收加密后的数据 */
    err = recvmsg_from_crypto(opfd2, decrypt_buf, plaintext_buf_len);
    if (err == -1) {
        goto recv_err;
    }
    printf("recvmsg_from_crypto txt: %s len: %ld\n\n", decrypt_buf,strlen(decrypt_buf));
    /*下面是两个使用其他接口操作编解码的实例*/
#elif RECV==1
    read(opfd2, decrypt_buf, plaintext_buf_len);
    printf("read txt: %s len: %ld\n", decrypt_buf,strlen(decrypt_buf));
#else
    err = recv(opfd2, decrypt_buf, plaintext_buf_len, 0);
    if (err == -1)
        perror("recv error:");
    else
        printf("recv txt: %s len: %ld\n\n", decrypt_buf,strlen(decrypt_buf));
#endif
 
bind_err:
setkey_err:
accept_err:
sendmsg_err:
recv_err:
    close(tfmfd);
    close(opfd);
    close(opfd2);
    free(plaintext_buf);
    free(encrypt_buf);
    free(decrypt_buf);
 
    return 0;
}
