#ifndef MAINWINDOW_H
#define MAINWINDOW_H

#include <QMainWindow>
#include <QWidget>
#include <QMouseEvent>
#include <QSizePolicy>
#include <QRect>
#include <QDebug>
#include <QQueue>
#include <QThread>
#include <QMutex>
#include <QTimer>
#include <QLabel>
#include <QtNetwork/QNetworkRequest>
#include <QtNetwork/QNetworkAccessManager>
#include <QtNetwork/QNetworkReply>
#include <QUrl>
#include <QKeyEvent>
#include <QJsonObject>
#include <QJsonParseError>
#include <QJsonDocument>
#include <QJsonArray>
#include <QPainter>
#include <QLayout>
#include <QLayoutItem>
#include <QFormLayout>
#include <QMenu>
#include <QComboBox>
#include <QVariant>
#include <QListWidget>
#include <QListWidgetItem>
#include <QScrollArea>
#include <QPlainTextEdit>
#include <QStandardItem>
#include <QLineEdit>
#include <QProcess>
#include <QNetworkInterface>
#include <QDateTime>
#include <QDialog>
#include <QCheckBox>
#include <QList>
#include <sys/time.h>
#include <sys/stat.h>
#include <algorithm>
#include <time.h>
#include <QMessageBox>
#include <QDir>
#include <QFile>
#include <QProcessEnvironment>
#include <QMetaType>
#include <QGuiApplication>

QT_BEGIN_NAMESPACE
namespace Ui { class MainWindow; }
QT_END_NAMESPACE

class MainWindow : public QMainWindow
{
    Q_OBJECT

public:
    MainWindow(QWidget *parent = nullptr);
    ~MainWindow();
    static QString executeLinuxCmd(QString strCmd);
    void _get_ip_info(QNetworkInterface interface);
    bool getDemos(void);
    void ShowDemosInf(bool show);
    QApplication* app;
    int fontId = -1;

public slots:

    void _show_current_time();
    void _wan_button_click_cb();
    void _lan_button_click_cb();
    void _flash_show_info();
    void _show_cmd_to_label(QLabel* label, QString cmd);

private slots:
    void on_lan_button_2_clicked();

    void on_show_net_button_clicked();

private:
    bool __set_network(const QString& dev_name,
        const QString& ipv4, const QString& ipv4_net,
        const QString& ipv4_gate, const QString& ipv4_dns,
        const QString& ipv6, const QString& ipv6_net,
        const QString& ipv6_gate, const QString& ipv6_dns);

    void checkIPv4(QLineEdit* edit, const QString& fieldName){
        if(edit->text().isEmpty())
            return;
        QHostAddress addr;
        if(addr.setAddress(edit->text()))
            if(addr.protocol() == QAbstractSocket::IPv4Protocol)
                if(addr.toString() == edit->text())
                    return;
        edit->clear();
        QMessageBox::warning(this, "ERROR", QString(tr("请输入合法的 IPv4 地址(%1)")).arg(fieldName));
        edit->setFocus();
    };

    bool isValidIPv4Mask(quint32 mask) {
        quint32 inverted = ~mask;
        if (mask == 0x00000000 || mask == 0xFFFFFFFF)
            return true;
        return ((inverted + 1) & inverted) == 0;
    }

    void checkIPv4SubnetMask(QLineEdit* edit, const QString& fieldName) {
        if (edit->text().isEmpty())
            return;
        bool ok;
        int cidr = edit->text().toInt(&ok);
        if (ok && cidr > 0 && cidr <= 32)
            return;
        QHostAddress addr;
        if (addr.setAddress(edit->text()))
            if (addr.protocol() == QAbstractSocket::IPv4Protocol)
                if (addr.toString() == edit->text())
                    if (edit->text() != "0.0.0.0")
                        if (isValidIPv4Mask((quint32)addr.toIPv4Address()))
                            return;
        edit->clear();
        QMessageBox::warning(this, "ERROR", QString(tr("请输入合法的子网掩码(%1)\n(格式：255.255.255.0 或 1-32)")).arg(fieldName));
        edit->setFocus();
    };

    void checkIPv6(QLineEdit* edit, const QString& fieldName){
        if(edit->text().isEmpty())
            return;
        QHostAddress addr;
        qDebug() << "checkIPv6";
        if(addr.setAddress(edit->text()))
            if(addr.protocol() == QAbstractSocket::IPv6Protocol)
                if(addr.toString() == edit->text())
                    return;
        edit->clear();
        QMessageBox::warning(this, "ERROR", QString(tr("请输入合法的 IPv6 地址(%1)")).arg(fieldName));
        edit->setFocus();
    };

    void checkIPv6SubnetMask(QLineEdit* edit, const QString& fieldName) {
        if (edit->text().isEmpty())
            return;
        bool ok;
        int prefixLength = edit->text().toInt(&ok);
        if (ok && prefixLength > 0 && prefixLength <= 128)
            return;
        edit->clear();
        QMessageBox::warning(this, "ERROR", QString(tr("请输入合法的 IPv6 子网掩码(%1)\n(格式：1-128 之间的数字，如 64)")).arg(fieldName));
        edit->setFocus();
    };

    Ui::MainWindow *ui;

    QTimer * time_clock;
    QTimer * ip_clock;

    QString network_info_eth0;
    QString network_info_eth1;

    QSet<QLabel*> runingComToQlabel;

    QProcessEnvironment env;
};

class MyMessageBox : public QMessageBox {
protected:
void showEvent(QShowEvent* event) {
QMessageBox::showEvent(event);
qDebug() << "set dialg size";
//setFixedSize(800*2, 600*2);
}
};
#endif // MAINWINDOW_H
