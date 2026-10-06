#ifndef FINETERMINAL_MAINWINDOW_H
#define FINETERMINAL_MAINWINDOW_H

#include <QMainWindow>
#include <functional>

class QTabWidget;
class QTermWidget;
class QTimer;
class QToolButton;
class QToolBar;

class MainWindow : public QMainWindow
{
    Q_OBJECT
public:
    explicit MainWindow(QWidget *parent = nullptr);

protected:
    bool eventFilter(QObject *obj, QEvent *event) override;
    void closeEvent(QCloseEvent *event) override;

private slots:
    void newTab();
    void closeTab(int index);
    void cycleTab();
    void lockNow();
    void showSettings();
    void applySettings();
    void updateTabTitle();

private:
    QTermWidget *currentTerminal() const;
    QTermWidget *terminalAt(int index) const;
    void buildToolbar();
    void rebuildQuickCommands();
    void addShortcut(const QKeySequence &seq, const std::function<void()> &fn);
    void zoom(int delta);

    QTabWidget *m_tabs;
    QToolBar *m_quickCmdBar = nullptr;
    QTimer *m_idleTimer = nullptr;
    int m_idleIdleSeconds = 0;
    bool m_closing = false;
};

#endif
