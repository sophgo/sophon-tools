#include "mainwindow.h"
#include "ui_mainwindow.h"
#include "qtermwidget.h"

#define GET_BASH_INFO_ASYNC 0

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

template <typename T>
static void __updateWidgets(T *inObject)
{
    inObject->update();
    QObject *object = inObject;
    QList<T *> childObjects = object->findChildren<T *>();
    for (T *childObject : childObjects)
    {
        __updateWidgets(childObject);
    }
}

QString MainWindow::executeLinuxCmd(QString strCmd)
{
    QProcess p;
    p.start("bash", QStringList() << "-c" << strCmd);
    p.waitForFinished();
    QString strResult = p.readAllStandardOutput();
    qDebug() << "run " + strCmd + " ret: " + strResult;
    return strResult;
}

void MainWindow::_show_cmd_to_label(QLabel* label, QString cmd)
{
#if GET_BASH_INFO_ASYNC
    if(runingComToQlabel.contains(label))
    {
        qWarning() << cmd << "is running, please check YOUR SOPHON_QT_* fun";
        return;
    }
    QProcess *process = new QProcess();
    QObject::connect(process, static_cast<void (QProcess::*)(int exitCode, QProcess::ExitStatus exitStatus)>(&QProcess::finished), this,
        [label,process,this](int exitCode, QProcess::ExitStatus exitStatus){
            Q_UNUSED(exitCode); 
            Q_UNUSED(exitStatus);
        QString ret = process->readAllStandardOutput();
        label->setText(ret);
        this->runingComToQlabel.remove(label);
        process->deleteLater();
    },Qt::QueuedConnection);
    runingComToQlabel.insert(label);
    process->start("bash", QStringList() << "-c" << cmd);
#else
    label->setText(executeLinuxCmd(cmd));
#endif
}

MainWindow::MainWindow(QWidget *parent)
    : QMainWindow(parent)
    , ui(new Ui::MainWindow)
{

    ui->setupUi(this);
    env = QProcessEnvironment::systemEnvironment();
    QString sophonBgPath = env.value("SOPHON_QT_BG_PATH");
    if(!sophonBgPath.isEmpty())
    {
        QString styleSheet = QString("MainWindow { border-image: url(%1); background-color: #000000;}").arg(sophonBgPath);
        this->setStyleSheet(styleSheet);
    }

    /* 时间显示 */
    time_clock = new QTimer(this);
    connect(time_clock, SIGNAL(timeout()), this, SLOT(_show_current_time()));
    time_clock->start(1000);

    ip_clock = new QTimer(this);
    connect(ip_clock, SIGNAL(timeout()), this, SLOT(_flash_show_info()));
    ip_clock->start(5000);

    connect(ui->wan_button, SIGNAL(clicked()), this,SLOT(_wan_button_click_cb()));
    connect(ui->lan_button, SIGNAL(clicked()), this, SLOT(_lan_button_click_cb()));
    connect(ui->wan_ip, &QLineEdit::editingFinished, this, [=]{ checkIPv4(ui->wan_ip, "WAN IPv4"); });
    connect(ui->wan_net, &QLineEdit::editingFinished, this, [=]{ checkIPv4SubnetMask(ui->wan_net, "WAN IPv4 NETMASK"); });
    connect(ui->wan_gate, &QLineEdit::editingFinished, this, [=]{ checkIPv4(ui->wan_gate, "WAN IPv4 GATEWAY"); });
    connect(ui->wan_dns, &QLineEdit::editingFinished, this, [=]{ checkIPv4(ui->wan_dns, "WAN IPv4 DNS"); });
    connect(ui->lan_ip, &QLineEdit::editingFinished, this, [=]{ checkIPv4(ui->lan_ip, "LAN IPv4"); });
    connect(ui->lan_net, &QLineEdit::editingFinished, this, [=]{ checkIPv4SubnetMask(ui->lan_net, "LAN IPv4 NETMASK"); });
    connect(ui->lan_gate, &QLineEdit::editingFinished, this, [=]{ checkIPv4(ui->lan_gate, "LAN IPv4 GATEWAY"); });
    connect(ui->lan_dns, &QLineEdit::editingFinished, this, [=]{ checkIPv4(ui->lan_dns, "LAN IPv4 DNS"); });
    connect(ui->wan_ip6, &QLineEdit::editingFinished, this, [=]{ checkIPv6(ui->wan_ip6, "WAN IPv6"); });
    connect(ui->wan_net6, &QLineEdit::editingFinished, this, [=]{ checkIPv6SubnetMask(ui->wan_net6, "WAN IPv6 NETMASK"); });
    connect(ui->wan_gate6, &QLineEdit::editingFinished, this, [=]{ checkIPv6(ui->wan_gate6, "WAN IPv6 GATEWAY"); });
    connect(ui->wan_dns6, &QLineEdit::editingFinished, this, [=]{ checkIPv6(ui->wan_dns6, "WAN IPv6 DNS"); });
    connect(ui->lan_ip6, &QLineEdit::editingFinished, this, [=]{ checkIPv6(ui->lan_ip6, "LAN IPv6"); });
    connect(ui->lan_net6, &QLineEdit::editingFinished, this, [=]{ checkIPv6SubnetMask(ui->lan_net6, "LAN IPv6 NETMASK"); });
    connect(ui->lan_gate6, &QLineEdit::editingFinished, this, [=]{ checkIPv6(ui->lan_gate6, "LAN IPv6 GATEWAY"); });
    connect(ui->lan_dns6, &QLineEdit::editingFinished, this, [=]{ checkIPv6(ui->lan_dns6, "LAN IPv6 DNS"); });

    _flash_show_info();

    ShowDemosInf(getDemos());
    static QTimer timerDemoInfoFlash;
    QObject::connect(&timerDemoInfoFlash, &QTimer::timeout, [&]() {
        ShowDemosInf(getDemos());
    });
    timerDemoInfoFlash.start(5000);
    qRegisterMetaType<qreal>("qreal");
}

MainWindow::~MainWindow()
{
    delete ui;
}

bool MainWindow::getDemos(void)
{
    QDir localDir = QCoreApplication::applicationDirPath();
    QDir demoDir(QString(localDir.absolutePath() + QDir::separator() + "demos"));
    if (!demoDir.exists())
        return false;
    QStringList demoFiles = demoDir.entryList(QStringList() << "*.demo", QDir::Files);
    if(demoFiles.isEmpty())
        return false;
    QSet<QString> comboBoxItems;
    for (int i = 0; i < ui->comboBoxSelectDemo->count(); ++i) {
        comboBoxItems.insert(ui->comboBoxSelectDemo->itemText(i));
    }
    QSet<QString> demoFilesSet = QSet<QString>::fromList(demoFiles);
    if (demoFilesSet == comboBoxItems)
        return true;
    ui->comboBoxSelectDemo->clear();
    ui->comboBoxSelectDemo->addItems(demoFiles);
    QObject::disconnect(ui->pushButtonRunDemo);
    QObject::connect(ui->pushButtonRunDemo, &QPushButton::clicked, [localDir,demoDir,this]() {
        QString SophUIDEMOPath = QString(demoDir.absolutePath()+QDir::separator() + this->ui->comboBoxSelectDemo->currentText());
        QString startFile = QString(localDir.absolutePath() + QDir::separator() + "SophUIDEMO.sh");
        QFile::remove(startFile);
        QFile fileSophUIDEMO(startFile);
        if (fileSophUIDEMO.open(QIODevice::WriteOnly | QIODevice::Text))
        {
            QTextStream streamSophUIDEMO(&fileSophUIDEMO);
            streamSophUIDEMO << "#!/usr/bin/bash" << endl;
            streamSophUIDEMO << "chmod +x " << SophUIDEMOPath << endl;
            streamSophUIDEMO << SophUIDEMOPath << endl;
            streamSophUIDEMO << "ret=$?" << endl;
            /* 由于当前的demo没有任何方式可以自主退出,所以假定demo永远正确地退出 */
            streamSophUIDEMO << "exit 0" << endl;
            streamSophUIDEMO << "exit $ret" << endl;
            fileSophUIDEMO.close();
        }
        QCoreApplication::quit();
    });
    return true;
}

void MainWindow::ShowDemosInf(bool show)
{
    ui->comboBoxSelectDemo->setDisabled(!show);
    ui->pushButtonRunDemo->setDisabled(!show);
    if(!show)
    {
        ui->comboBoxSelectDemo->hide();
        ui->pushButtonRunDemo->hide();
        ui->INFO_3->hide();
        ui->line_3->hide();
    }
    else
    {
        ui->comboBoxSelectDemo->show();
        ui->pushButtonRunDemo->show();
        ui->INFO_3->show();
        ui->line_3->show();
    }
}

void MainWindow::_get_ip_info(QNetworkInterface interface)
{
    QList<QString> ip_str_list;
    QList<QString> ip_str_v6_list;
    QString mac_str;
    QString device_name = interface.name();
    QString *info_str = nullptr;
    if(interface.name() == "eth0")
        info_str = &network_info_eth0;
    else if(interface.name() == "eth1")
        info_str = &network_info_eth1;
    mac_str = interface.hardwareAddress().toUtf8();
    QList<QNetworkAddressEntry>addressList = interface.addressEntries();
    foreach(QNetworkAddressEntry _entry, addressList)
    {
        QHostAddress address = _entry.ip();
        address.setScopeId(QString());
        if(address.protocol() == QAbstractSocket::IPv4Protocol)
            ip_str_list.append(QString("%1/%2").arg(address.toString()).arg(_entry.prefixLength()));
        else if(address.protocol() == QAbstractSocket::IPv6Protocol)
            ip_str_v6_list.append(QString("%1/%2").arg(address.toString()).arg(_entry.prefixLength()));
    }
    qDebug() << "mac: " << mac_str << " ip: " << ip_str_list.toStdList();
    if(info_str != nullptr) {
        *info_str =      "  MAC:\t" + mac_str+ "\n";
        *info_str +=    "  IPv4:";
        foreach(QString _entry, ip_str_list)
            *info_str += "\t" + _entry + "\n";
        if(ip_str_list.empty())
            *info_str += "\n";
        *info_str +=    "  IPv6:";
        foreach(QString _entry, ip_str_v6_list)
            *info_str += "\t" + _entry + "\n";
    }
}

void MainWindow::_flash_show_info()
{
    foreach (QNetworkInterface netInterface, QNetworkInterface::allInterfaces())
    {
        _get_ip_info(netInterface);
    }
    ui->ip_detail->setText("WAN(eth0):\n" + network_info_eth0 + "\nLAN(eth1):\n" + network_info_eth1);
    _show_cmd_to_label(ui->info_detail,"SOPHON_QT_1");
    _show_cmd_to_label(ui->info_detail_2,"SOPHON_QT_2");
#if GET_BASH_INFO_ASYNC
    this->update();
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wdeprecated-declarations"
    app->flush();
#pragma GCC diagnostic pop
#endif
}

void MainWindow::_show_current_time()
{
    QDateTime *date_time = new QDateTime(QDateTime::currentDateTime());
    ui->TIME_LABLE->setText(QString("%1\n").arg(date_time->toString("hh:mm:ss"))
              + QString("%1").arg(date_time->toString("yyyy-MM-dd ddd")));
    delete date_time;
}

bool MainWindow::__set_network(
    const QString& dev_name,
    const QString& ipv4, const QString& ipv4_net,
    const QString& ipv4_gate, const QString& ipv4_dns,
    const QString& ipv6, const QString& ipv6_net,
    const QString& ipv6_gate, const QString& ipv6_dns) {

    MyMessageBox msgBox;
    __setFontRecursively<QWidget>(&msgBox);

    msgBox.setWindowTitle("WARNING!");
    msgBox.setText("Question?");
    msgBox.setStandardButtons(QMessageBox::Yes | QMessageBox::No);
    msgBox.setDefaultButton(QMessageBox::No);

    QString ipv4_set_str;
    QString ipv6_set_str;

    if(!ipv4.isEmpty() && ipv4_net.isEmpty()) {
        msgBox.setInformativeText(tr("子网掩码不能为空"));
        msgBox.setStandardButtons(QMessageBox::Yes);
        msgBox.exec();
        msgBox.setStandardButtons(QMessageBox::Yes | QMessageBox::No);
        return false;
    }
    if(!ipv6.isEmpty() && ipv6_net.isEmpty()) {
        msgBox.setInformativeText(tr("子网掩码不能为空"));
        msgBox.setStandardButtons(QMessageBox::Yes);
        msgBox.exec();
        msgBox.setStandardButtons(QMessageBox::Yes | QMessageBox::No);
        return false;
    }
    if(ipv4.isEmpty())
        ipv4_set_str = QString("auto '' '' ''");
    else
        ipv4_set_str = QString("'%1' '%2' '%3' '%4'")
                           .arg(ipv4).arg(ipv4_net).arg(ipv4_gate).arg(ipv4_dns);
    if(ipv6.isEmpty())
        ipv6_set_str = QString("auto '' '' ''");
    else
        ipv6_set_str = QString("'%1' '%2' '%3' '%4'")
                       .arg(ipv6).arg(ipv6_net).arg(ipv6_gate).arg(ipv6_dns);
    QString msg_str;
    msg_str += QString("dev: %1\n\n").arg(dev_name);
    msg_str += "IPv4:\n";
    msg_str += QString("  address: %1\n").arg(ipv4.isEmpty() ? "DHCP AUTO" : ipv4);
    msg_str += QString("  network: %1\n").arg(ipv4.isEmpty() ? "DHCP AUTO" : ipv4_net);
    msg_str += QString("  gateway: %1\n").arg(ipv4.isEmpty() ? "DHCP AUTO" : ipv4_gate);
    msg_str += QString("  DNS: %1\n\n").arg(ipv4.isEmpty() ? "DHCP AUTO" : ipv4_dns);
    msg_str += "IPv6:\n";
    msg_str += QString("  address6: %1\n").arg(ipv6.isEmpty() ? "DHCP AUTO" : ipv6);
    msg_str += QString("  network6: %1\n").arg(ipv6.isEmpty() ? "DHCP AUTO" : ipv6_net);
    msg_str += QString("  gateway6: %1\n").arg(ipv6.isEmpty() ? "DHCP AUTO" : ipv6_gate);
    msg_str += QString("  DNS: %1\n").arg(ipv6.isEmpty() ? "DHCP AUTO" : ipv6_dns);
    msgBox.setInformativeText(msg_str);
    if(msgBox.exec() == QMessageBox::Yes) {
        executeLinuxCmd("bm_set_ip " + dev_name + " " + ipv4_set_str + " " + ipv6_set_str);
        return true;
    }
    return false;
}

void MainWindow::_wan_button_click_cb()
{
    if(true == __set_network("eth0",
                              ui->wan_ip->text(), ui->wan_net->text(),
                              ui->wan_gate->text(), ui->wan_dns->text(),
                              ui->wan_ip6->text(), ui->wan_net6->text(),
                              ui->wan_gate6->text(), ui->wan_dns6->text())) {
        ui->wan_ip->clear();
        ui->wan_net->clear();
        ui->wan_gate->clear();
        ui->wan_dns->clear();
        ui->wan_ip6->clear();
        ui->wan_net6->clear();
        ui->wan_gate6->clear();
        ui->wan_dns6->clear();
    }
}
void MainWindow::_lan_button_click_cb()
{
    if(true == __set_network("eth1",
                              ui->lan_ip->text(), ui->lan_net->text(),
                              ui->lan_gate->text(), ui->lan_dns->text(),
                              ui->lan_ip6->text(), ui->lan_net6->text(),
                              ui->lan_gate6->text(), ui->lan_dns6->text())) {
        ui->lan_ip->clear();
        ui->lan_net->clear();
        ui->lan_gate->clear();
        ui->lan_dns->clear();
        ui->lan_ip6->clear();
        ui->lan_net6->clear();
        ui->lan_gate6->clear();
        ui->lan_dns6->clear();
    }
}

void MainWindow::on_lan_button_2_clicked()
{
    executeLinuxCmd("SOPHON_QT_4");
}

static QString qtKeyToEscapeSequence(Qt::Key key) {
    static const QHash<Qt::Key, QString> keyMap = {
        // Cursor keys
        {Qt::Key_Up, "\033[A"},
        {Qt::Key_Down, "\033[B"},
        {Qt::Key_Right, "\033[C"},
        {Qt::Key_Left, "\033[D"},
        // Function keys
        {Qt::Key_F1, "\033OP"},
        {Qt::Key_F2, "\033OQ"},
        {Qt::Key_F3, "\033OR"},
        {Qt::Key_F4, "\033OS"},
        {Qt::Key_F5, "\033[15~"},
        {Qt::Key_F6, "\033[17~"},
        {Qt::Key_F7, "\033[18~"},
        {Qt::Key_F8, "\033[19~"},
        {Qt::Key_F9, "\033[20~"},
        {Qt::Key_F10, "\033[21~"},
        {Qt::Key_F11, "\033[23~"},
        {Qt::Key_F12, "\033[24~"},
        // Control keys
        {Qt::Key_Insert, "\033[2~"},
        {Qt::Key_Delete, "\033[3~"},
        {Qt::Key_Home, "\033[H"},
        {Qt::Key_End, "\033[F"},
        // {Qt::Key_PageUp, "\033[5~"},
        // {Qt::Key_PageDown, "\033[6~"},
        {Qt::Key_Escape, "\033"},
        {Qt::Key_Tab, "\t"},
        {Qt::Key_Backspace, "\b"},
        {Qt::Key_Return, "\r"},
        {Qt::Key_Enter, "\n"},
    };

    static const QHash<Qt::Key, QString> keyMap_x11 = {
        // Cursor keys
        {Qt::Key_Up, "\033[A"},
        {Qt::Key_Down, "\033[B"},
        {Qt::Key_Right, "\033[C"},
        {Qt::Key_Left, "\033[D"},
    };

    if (QString("5.14.0") == qVersion())
        return keyMap.value(key, QString());
    else
        return keyMap_x11.value(key, QString());
}

void MainWindow::on_show_net_button_clicked()
{
    int typeId = QMetaType::type("qreal");
    QString typeName = QMetaType::typeName(typeId);
    qDebug() << "qreal is " << typeName;
    if (typeName == "float") {
        qDebug() << "qreal = float";
        MyMessageBox msgBox;
        __setFontRecursively<QWidget>(&msgBox);

        msgBox.setWindowTitle("WARNING!");
        msgBox.setText("qt runtime In the Qt runtime environment, qreal is of type float,"
                       " and this feature is not supported, please update qt runtime");
        msgBox.setStandardButtons(QMessageBox::Yes);
        msgBox.setDefaultButton(QMessageBox::Yes);
        msgBox.exec();
        return;
    }
    QString login_user = env.value("SOPHON_QT_LOGIN_USER");
    login_user = login_user.isEmpty() ? "linaro" : login_user;
    qDebug() << "login user:" << login_user;
    QDialog dialog;
    QTermWidget *console = new QTermWidget(&dialog);
    QPushButton *closeButton = new QPushButton("Close",&dialog);
    console->setShellProgram("/bin/bash");
    console->changeDir("/");
    console->setWorkingDirectory("/");
    console->sendText(QString("export TERM=xterm\n"));
    console->sendText("clear\n");
    console->sendText(QString("echo 'login user: " + login_user + 
                    "'; login " + login_user + "; exit 0;\n"));
    console->setColorScheme(":/new/prefix1/WhiteOnBlack.colorscheme");
    if (fontId != -1) {
        QStringList fontFamilies = QFontDatabase::applicationFontFamilies(fontId);
        if (!fontFamilies.empty()) {
            QFont font(fontFamilies.at(0));
            int fontSize = 15;
            QString fontSizeStr = env.value("SOPHON_QT_FONT_SIZE");
            fontSize = fontSizeStr.toInt() > 0?fontSizeStr.toInt():fontSize;
            font.setPixelSize(fontSize);
            closeButton->setFont(font);
            console->setTerminalFont(font);
        }
    }

    QScrollArea *scrollArea = new QScrollArea(&dialog);
    QVBoxLayout *boxLayout = new QVBoxLayout(&dialog);
    scrollArea->setWidget(console);
    scrollArea->setWidgetResizable(true);
    dialog.resize(this->frameGeometry().width(),this->frameGeometry().height());
    dialog.setWindowTitle("QT Term");
    console->setScrollBarPosition(QTermWidget::ScrollBarRight);
    dialog.setLayout(boxLayout);
    QObject::connect(closeButton, &QPushButton::clicked, &dialog, &QDialog::accept);
    QObject::connect(console, &QTermWidget::finished, &dialog, &QDialog::accept);
    connect(console, &QTermWidget::termKeyPressed, [&](QKeyEvent *event) {
        qDebug() << "Key" << event;
        if (event->type() == QEvent::KeyPress) {
            console->sendText(qtKeyToEscapeSequence((Qt::Key)event->key()));
        };
    });
    dialog.layout()->addWidget(scrollArea);
    dialog.layout()->addWidget(closeButton);
    dialog.exec();
}

