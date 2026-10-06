cmake_minimum_required(VERSION 3.16)
project(FineTerminal VERSION 1.0.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_AUTOMOC ON)
set(CMAKE_AUTORCC ON)

find_package(Qt5 5.15 REQUIRED COMPONENTS Widgets)
find_package(qtermwidget5 REQUIRED)

add_executable(fineterminal
    src/main.cpp
    src/mainwindow.cpp
    src/settings.cpp
    src/settingsdialog.cpp
    src/lockscreen.cpp
    resources/fineterminal.qrc
)

target_include_directories(fineterminal PRIVATE src)

# 支持从解包的 dev 前缀取头文件（如 fnOS TrimRepo 缺 libqtermwidget5-1-dev）
if(QTERMWIDGET5_ROOT)
    target_include_directories(fineterminal PRIVATE ${QTERMWIDGET5_ROOT}/usr/include)
endif()

target_link_libraries(fineterminal PRIVATE Qt5::Widgets qtermwidget5)

install(TARGETS fineterminal RUNTIME DESTINATION bin)
