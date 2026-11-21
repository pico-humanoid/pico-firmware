"""Native PC CAN1/2/3 diagnostic entry point, sharing the serial test engine."""
from can_pc_test import PCTest

if __name__=='__main__':
    app=PCTest(multi=True)
    app.window.mainloop()
