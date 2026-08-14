#include "mainwindow.h"

#include <QApplication>
#include <QProcessEnvironment>
#include <QFont>
#include <QString>
#include <QFile>
#include <QSize>
#include <QFontDatabase>
#include <QScreen>
#include <QTranslator>

template <typename T>
static void __setFontRecursively(T *inObject, qint64 fontSize=15)
{
    QProcessEnvironment env = QProcessEnvironment::systemEnvironment();
    QString fontSizeStr = env.value("SOPHON_QT_FONT_SIZE");
    fontSize = fontSizeStr.toInt() > 0?fontSizeStr.toInt():fontSize;
    QFont font = inObject->font();
    font.setPixelSize(fontSize);
    inObject->setFont(font);
    QObject *object = inObject;
    QList<T *> childObjects = object->findChildren<T *>();
    for (T *childObject : childObjects)
    {
        __setFontRecursively(childObject,fontSize);
    }
}

static QSize getPrimaryResolution() {
    QScreen *primaryScreen = QGuiApplication::primaryScreen();
    if (primaryScreen) {
        return primaryScreen->size();
    }
    return QSize(1920, 1080); // Default resolution if primary screen is not found
}

static QtMsgType infoLimit = QtWarningMsg;

int main(int argc, char *argv[])
{
    QApplication a(argc, argv);
    QTranslator en;
    __setFontRecursively<QApplication>(&a);
    int fontId =
        QFontDatabase::addApplicationFont(":/font.file");
    if (fontId != -1) {
        QStringList fontFamilies = QFontDatabase::applicationFontFamilies(fontId);
        if (!fontFamilies.empty())
            QApplication::setFont(QFont(fontFamilies.at(0)));
    }
    QProcessEnvironment env = QProcessEnvironment::systemEnvironment();
    QString enEnable = env.value("SOPHON_QT_EN_ENABLE");
    if(enEnable == "1") {
        qDebug() << "enable english mode";
        bool flag = en.load(":/new/prefix1/en_US.qm");
        if(flag){
            qDebug() << "qm file load sucess";
            qApp->installTranslator(&en);
        }else
            qDebug() << "qm file load error";
    }
    QString env_info_limit = env.value("SOPHON_QT_CMD_DEBUG");
    if(env_info_limit == "1")
        infoLimit = QtDebugMsg;
    qSetMessagePattern("%{type}: %{message}");
    qInstallMessageHandler([](QtMsgType type, const QMessageLogContext &, const QString &msg) {
        if (type >= infoLimit) {
            QTextStream(stdout) << msg << endl;
        }
    });

    MainWindow w;
    QString device_name = MainWindow::executeLinuxCmd("awk -F': ' '/model name/{print $2; exit}' /proc/cpuinfo").trimmed();
    // CV84X2（SDK 标识 cv84x6）内核 compat 模式下 model name 可能为 null/空/cv186ah；
    // 以 dts 递归含 "cvitek,cv84x6-" compatible 权威识别（与 get_info 一致），归一化后与 bm1688/cv186ah
    // 同走 CV 家族的原生 DRM(card0) HDMI 通路与全屏尺寸逻辑。
    if (device_name != "bm1688" && device_name != "cv186ah" && device_name != "cv84x6") {
        QString dtsMatch = MainWindow::executeLinuxCmd(
            "find /proc/device-tree -name compatible -type f -exec grep -laE 'cvitek,cv84x6-' {} + 2>/dev/null | grep -c .").trimmed();
        if (dtsMatch.toInt() > 0)
            device_name = "cv84x6";
    }
    qDebug() << device_name;
    /* 根据设备名解析 WAN/LAN 实际网口名(ubuntu: eth0/eth1,debian: end0/end1) */
    w.resolveNetworkIfnames(device_name);
    w.fontId = fontId;
    w.app = &a;
    if (device_name == "bm1688" || device_name == "cv186ah" || device_name == "cv84x6"){
        QScreen *primaryScreen = QGuiApplication::primaryScreen();
        int screenWidth = primaryScreen->size().width();; // 屏幕分辨率
        int screenHeight= primaryScreen->size().height(); // 屏幕分辨率高度
        qDebug() << "Display size" << screenWidth << screenHeight;
        //change font size according to current dpi
        qreal dpi = primaryScreen->logicalDotsPerInch();
        QString fontSizeStr = env.value("SOPHON_QT_FONT_SIZE");
        qint64 fontSize = fontSizeStr.toInt() > 0 ? fontSizeStr.toInt() : 15;
        fontSize = fontSize * screenHeight / 1080;
        qputenv("SOPHON_QT_FONT_SIZE", QString::number(fontSize).toUtf8());
        //resize before show window
        w.resize(screenWidth, screenHeight);
    }else{
        QString platform = QGuiApplication::platformName();
        qDebug() << "Current platform:" << platform;
        QSize primaryResolution = getPrimaryResolution();
        qDebug() << "Primary screen resolution:" << primaryResolution;
        w.showFullScreen();
        w.setFixedSize(primaryResolution);
    }
    __setFontRecursively<QWidget>(&w);
    w.show();
    return a.exec();
}
