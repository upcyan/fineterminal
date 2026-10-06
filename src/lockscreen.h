#ifndef FINETERMINAL_LOCKSCREEN_H
#define FINETERMINAL_LOCKSCREEN_H

#include <QDialog>
#include <QLabel>
#include <QLineEdit>
#include <QPushButton>

// 应用锁屏：启动时 / 手动 / 空闲超时时遮挡整个窗口，输对密码才能继续。
class LockScreen : public QDialog
{
    Q_OBJECT
public:
    explicit LockScreen(QWidget *parent = nullptr);

    // 首次设置密码模式：需要输入两次
    void setSetupMode(bool setup);

protected:
    void showEvent(QShowEvent *e) override;
    void keyPressEvent(QKeyEvent *e) override;

private slots:
    void tryUnlock();

private:
    void applySetupUi();

    QLabel *m_title;
    QLineEdit *m_edit;
    QLineEdit *m_edit2;
    QLabel *m_hint;
    QPushButton *m_ok;
    bool m_setupMode = false;
    int m_failed = 0;
};

#endif
