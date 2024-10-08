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
    font.setPointSize(fontSize);
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
    qDebug() << strResult  + strCmd;
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

    QRegExp rx("\\b(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\\b");
    ui->wan_ip->setValidator(new QRegExpValidator(rx, this));
    ui->wan_net->setValidator(new QRegExpValidator(rx, this));
    ui->wan_gate->setValidator(new QRegExpValidator(rx, this));
    ui->wan_dns->setValidator(new QRegExpValidator(rx, this));

    ui->lan_ip->setValidator(new QRegExpValidator(rx, this));
    ui->lan_net->setValidator(new QRegExpValidator(rx, this));
    ui->lan_gate->setValidator(new QRegExpValidator(rx, this));
    ui->lan_dns->setValidator(new QRegExpValidator(rx, this));

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
    QString ip_str;
    QString netmask_str;
    QString gateway_str;
    QString dns_str;

    QString mac_str;
    QString device_name = interface.name();
    mac_str = interface.hardwareAddress().toUtf8();
    QList<QNetworkAddressEntry>addressList = interface.addressEntries();
    foreach(QNetworkAddressEntry _entry, addressList)
    {
        QHostAddress address = _entry.ip();
        if(address.protocol() == QAbstractSocket::IPv4Protocol)
        {
            ip_str = address.toString();
            netmask_str = _entry.netmask().toString();
        }
    }
    qDebug() << "mac: " << mac_str << " ip: " << ip_str << " netmask: " << netmask_str;
    if(interface.name() == "eth0")
    {
        wan_mac =     "WAN(eth0) \n            MAC:      " + mac_str+ "\n";
        wan_ip =            "            IP:       " +ip_str+ "\n";
        wan_netmask =       "            NETMASK:  " +netmask_str+ "\n";
    }
    else if(interface.name() == "eth1")
    {
        lan_mac =     "LAN(eth1) \n            MAC:      " +mac_str + "\n";
        lan_ip =            "            IP:       " +ip_str+ "\n";
        lan_netmask =       "            NETMASK:  " +netmask_str+ "\n";
    }
}

void MainWindow::_flash_show_info()
{
    foreach (QNetworkInterface netInterface, QNetworkInterface::allInterfaces())
    {
        _get_ip_info(netInterface);
    }
    ui->ip_detail->setText(wan_mac+wan_ip+wan_netmask+lan_mac+lan_ip+lan_netmask);
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
    ui->TIME_LABLE->setText(tr("%1\n").arg(date_time->toString("hh:mm:ss"))
              + tr("%1").arg(date_time->toString("yyyy-MM-dd ddd")));
    delete date_time;
}

void MainWindow::_wan_button_click_cb()
{
    QString set_str;
    bool flag = false;

    MyMessageBox msgBox;
    __setFontRecursively<QWidget>(&msgBox);
    // msgBox.setFixedSize(640*4,480*4);//设置MessageBox的大小

    msgBox.setWindowTitle("WARNING!");
    msgBox.setText("Question?");
    msgBox.setStandardButtons(QMessageBox::Yes | QMessageBox::No);
    msgBox.setDefaultButton(QMessageBox::No);


    if(ui->wan_ip->text().isEmpty() && ui->wan_net->text().isEmpty() && ui->wan_gate->text().isEmpty() && ui->wan_dns->text().isEmpty())
    {
        qDebug() << QStringLiteral("Input exmpty will set to dhcp!");

        msgBox.setInformativeText(tr("WAN(eth0)将会设置成动态IP模式"));
        int ret = msgBox.exec();
        if( ret == QMessageBox::Yes)
        {
            qDebug() << QStringLiteral("set ip to dhcp!");
            /* set_ip */
            executeLinuxCmd("bm_set_ip_auto eth0");
            flag = true;
        }
    }
    else
    {
        QString _ip = ui->wan_ip->text();
        QString _netmask = ui->wan_net->text();
        QString _gateway = ui->wan_gate->text();
        QString _dns = ui->wan_dns->text();

        set_str = "IP: " +_ip +"\nNETMASK: " + _netmask + "\nGATEWAY: "  +_gateway +"\nDNS: " + _dns;

        msgBox.setInformativeText(set_str);
        if (ui->wan_net->text().isEmpty()){
            msgBox.setInformativeText(tr("子网掩码不能为空"));
            msgBox.setStandardButtons(QMessageBox::Yes);
            msgBox.exec();
            msgBox.setStandardButtons(QMessageBox::Yes | QMessageBox::No);
            return;
        }
        else if (ui->wan_net->text() == "0.0.0.0"){
            msgBox.setInformativeText(tr("无效的子网掩码:0.0.0.0"));
            msgBox.setStandardButtons(QMessageBox::Yes);
            msgBox.exec();
            msgBox.setStandardButtons(QMessageBox::Yes | QMessageBox::No);
            return;
        }
        if (ui->wan_gate->text().isEmpty())
            _gateway="\"\"";
        if (ui->wan_dns->text().isEmpty())
            _dns="\"\"";
        qDebug() << ":" + _netmask + ":" + _gateway +":" +_dns ;
        int ret = msgBox.exec();
        if( ret == QMessageBox::Yes)
        {
            qDebug() << QStringLiteral("set ip to static!");
            /* set_ip */
            executeLinuxCmd("bm_set_ip eth0 " + _ip + " " +_netmask + " " + _gateway+ " " + _dns);
            flag = true;
        }
    }
    if (flag == true)
    {
        ui->wan_ip->setText("");
        ui->wan_net->setText("");
        ui->wan_gate->setText("");
        ui->wan_dns->setText("");
    }

}
void MainWindow::_lan_button_click_cb()
{
    QString set_str;
    bool flag = false;

    MyMessageBox msgBox;
    __setFontRecursively<QWidget>(&msgBox);
    // msgBox.setFixedSize(640*4,480*4);//设置MessageBox的大小

    msgBox.setWindowTitle("WARNING!");
    msgBox.setText("Question?");
    msgBox.setStandardButtons(QMessageBox::Yes | QMessageBox::No);
    msgBox.setDefaultButton(QMessageBox::No);

    if(ui->lan_ip->text().isEmpty() && ui->lan_net->text().isEmpty() && ui->lan_gate->text().isEmpty() && ui->lan_dns->text().isEmpty())
    {
        qDebug() << QStringLiteral("Input exmpty will set to dhcp!");
        msgBox.setInformativeText(tr("LAN(eth1)将会设置成动态IP模式"));
        int ret = msgBox.exec();
        if( ret == QMessageBox::Yes)
        {
            qDebug() << QStringLiteral("set ip to dhcp!");
            /* set_ip */
            executeLinuxCmd("bm_set_ip_auto eth1");
            flag = true;
        }
    }
    else
    {
        QString _ip = ui->lan_ip->text();
        QString _netmask = ui->lan_net->text();
        QString _gateway = ui->lan_gate->text();
        QString _dns = ui->lan_dns->text();

        set_str = "IP: " +_ip +"\nNETMASK: " + _netmask + "\nGATEWAY: "  +_gateway +"\nDNS: " + _dns;

        //int ret = MyMessageBox::warning(this, QStringLiteral("warning!"), set_str, QMessageBox::Cancel | QMessageBox::Ok);
        msgBox.setInformativeText(set_str);
        if (ui->lan_net->text().isEmpty()){
            msgBox.setInformativeText(tr("子网掩码不能为空"));
            msgBox.setStandardButtons(QMessageBox::Yes);
            msgBox.exec();
            msgBox.setStandardButtons(QMessageBox::Yes | QMessageBox::No);
            return;
        }
        else if (ui->lan_net->text() == "0.0.0.0"){
            msgBox.setInformativeText(tr("无效的子网掩码:0.0.0.0"));
            msgBox.setStandardButtons(QMessageBox::Yes);
            msgBox.exec();
            msgBox.setStandardButtons(QMessageBox::Yes | QMessageBox::No);
            return;
        }
        if (ui->lan_gate->text().isEmpty())
            _gateway="\"\"";
        if (ui->lan_dns->text().isEmpty())
            _dns="\"\"";
        int ret = msgBox.exec();
        if( ret == QMessageBox::Yes)
        {
            qDebug() << QStringLiteral("set ip to static!");
            /* set_ip */
            executeLinuxCmd("bm_set_ip eth1 " + _ip + " " +_netmask + " " + _gateway+ " " + _dns);
            flag = true;
        }
    }
    if (flag == true)
    {
        ui->lan_ip->setText("");
        ui->lan_net->setText("");
        ui->lan_gate->setText("");
        ui->lan_dns->setText("");
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

