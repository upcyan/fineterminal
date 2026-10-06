#include "mainwindow.h"
#include "settings.h"
#include "lockscreen.h"

#include <QApplication>
#include <QProcessEnvironment>

int main(int argc, char *argv[])
{
    QApplication app(argc, argv);
    app.setApplicationName(QStringLiteral("FineTerminal"));
    app.setOrganizationName(QStringLiteral("FineTerminal"));
    app.setWindowIcon(QIcon(QStringLiteral(":/icons/fineterminal.svg")));

    Settings::instance().load();

    MainWindow win;

    // 启动时锁定
    Settings &st = Settings::instance();
    if (st.lockOnStart()) {
        if (!st.hasPassword()) {
            LockScreen setup(&win);
            setup.setSetupMode(true);
            setup.exec();
        } else {
            LockScreen lock(&win);
            lock.exec();
        }
    }

    win.show();
    return app.exec();
}
