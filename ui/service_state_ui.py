"""State observations cross into Tk through a mailbox, never a worker callback."""
import queue
from core.system_state import state_manager

class StateBinding:
    def __init__(self,root,callback,widget=None):
        self.root=root;self.callback=callback;self.widget=widget;self.closed=False
        self.mailbox=queue.Queue(1)
        self.token=state_manager.subscribe_all(self._notice)
        self.after=None;self._notice(None);self._drain()
        if widget is not None:
            widget.bind('<Destroy>',lambda event:self.close() if event.widget is widget else None,add='+')
    def _notice(self,state):
        try:self.mailbox.put_nowait(True)
        except queue.Full:pass
    def _drain(self):
        if self.closed:return
        if self.widget is not None and not self.widget.winfo_exists():self.close();return
        try:
            self.mailbox.get_nowait();self.callback(state_manager.snapshot())
        except queue.Empty:pass
        self.after=self.root.after(250,self._drain)
    def close(self):
        if self.closed:return
        self.closed=True;state_manager.unsubscribe(self.token)
        if self.after is not None:
            try:self.root.after_cancel(self.after)
            except Exception:pass
class EventBinding:
    """Notificaciones del bus a Tk mediante buzón coalescente y ciclo de vida del widget."""
    def __init__(self,root,callback,widget,types):
        import queue
        from core.event_bus import event_bus
        self.root=root;self.widget=widget;self.callback=callback;self.cerrado=False
        self.queue=queue.Queue(maxsize=1)
        def recibir(event):
            try:self.queue.put_nowait(event)
            except queue.Full:pass
        self.subscription=event_bus.subscribe(types,recibir,name='vista:'+str(id(self)))
        self.after=root.after(200,self.consumir)
        widget.bind('<Destroy>',lambda event:self.close() if event.widget is widget else None,add='+')
    def consumir(self):
        import queue
        if self.cerrado:return
        try:event=self.queue.get_nowait()
        except queue.Empty:pass
        else:self.callback(event)
        if not self.cerrado:self.after=self.root.after(200,self.consumir)
    def close(self):
        self.cerrado=True;self.subscription.unsubscribe()
        try:self.root.after_cancel(self.after)
        except Exception:pass

