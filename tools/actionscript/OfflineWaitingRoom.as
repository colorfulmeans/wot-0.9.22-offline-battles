package {
    import flash.display.DisplayObject;
    import flash.display.DisplayObjectContainer;
    import flash.events.Event;
    import flash.geom.Point;
    import flash.geom.Rectangle;
    import flash.text.TextField;
    import flash.text.TextFormat;
    import flash.utils.getDefinitionByName;
    import flash.utils.getQualifiedClassName;
    import net.wg.infrastructure.base.AbstractWindowView;
    import scaleform.clik.data.DataProvider;
    import scaleform.clik.events.ButtonEvent;
    import scaleform.clik.events.ListEvent;

    // Compiled against #1513; the builder gives this movie its own class name.
    public dynamic class TrainingWindow extends AbstractWindowView {
        public var offlineAction:Function;
        private var fields:Object = {};
        private var widgets:Object = {};
        private var updating:Boolean = false;
        private var queue:Object;
        private var bodyFormat:TextFormat;
        private var embedded:Boolean;

        public function TrainingWindow() { super(); }

        override protected function configUI():void {
            bodyFormat = this["battleType"].defaultTextFormat;
            embedded = this["battleType"].embedFonts;
            bodyFormat.size = 13;
            bodyFormat.color = 11711136;
            while (numChildren) removeChildAt(0);
            graphics.beginFill(0, 0);
            graphics.drawRect(0, 0, 620, 244);
            graphics.endFill();
            setSize(620, 244);
            super.configUI();
            text("room", 0, 2, 620);
            text("players", 0, 24, 620);
            text("tierLabel", 0, 47, 292);
            text("skillLabel", 316, 47, 304);
            dropdown("tier", 0, 65, 292);
            dropdown("skill", 316, 65, 304);
            button("map", "ButtonNormal", 0, 97, 464);
            button("random", "ButtonNormal", 476, 97, 144);
            text("size1Label", 0, 126, 292);
            text("size2Label", 316, 126, 304);
            dropdown("size1", 0, 144, 292);
            dropdown("size2", 316, 144, 304);
            button("team1", "ButtonNormal", 0, 177, 196);
            button("team_random", "ButtonNormal", 212, 177, 196);
            button("team2", "ButtonNormal", 424, 177, 196);
            text("message", 0, 202, 620);
            button("start", "ButtonRed", 338, 222, 180);
            button("close", "ButtonBlack", 526, 222, 94);
        }

        private function text(key:String, xPos:Number, yPos:Number, w:Number):void {
            var label:TextField = new TextField();
            label.defaultTextFormat = bodyFormat;
            label.embedFonts = embedded;
            label.selectable = false;
            label.mouseEnabled = false;
            label.x = xPos; label.y = yPos; label.width = w; label.height = 21;
            fields[key] = label;
            addChild(label);
        }

        private function component(key:String, linkage:String, xPos:Number, yPos:Number, w:Number):Object {
            var cls:Class = getDefinitionByName(linkage) as Class;
            var item:Object = new cls();
            item.name = key;
            item.x = xPos; item.y = yPos; item.width = w; item.height = 22;
            item.enabled = true;
            item.enableInitCallback = false;
            widgets[key] = item;
            addChild(item as DisplayObject);
            return item;
        }

        private function button(key:String, linkage:String, xPos:Number, yPos:Number, w:Number):void {
            var item:Object = component(key, linkage, xPos, yPos, w);
            item.addEventListener(ButtonEvent.CLICK, clicked);
        }

        private function dropdown(key:String, xPos:Number, yPos:Number, w:Number):void {
            var item:Object = component(key, "DropdownMenuUI", xPos, yPos, w);
            item.dropdown = "DropdownMenu_ScrollingList";
            item.itemRenderer = "DropDownListItemRendererSoundUI";
            item.menuRowCount = 8;
            item.rowHeight = 20;
            item.addEventListener(ListEvent.INDEX_CHANGE, selected);
        }

        private function clicked(event:ButtonEvent):void {
            if (!updating && offlineAction != null) offlineAction(event.currentTarget.name, "");
        }

        private function selected(event:ListEvent):void {
            if (updating || offlineAction == null) return;
            var item:Object = event.currentTarget;
            if (item.selectedIndex >= 0) offlineAction(item.name, item.dataProvider[item.selectedIndex].value);
        }

        public function as_update(data:Object):void {
            updating = true;
            window.title = data.title;
            window.useBottomBtns = true;
            for (var key:String in fields) fields[key].text = data.labels[key] || "";
            for (key in widgets) {
                var widget:Object = widgets[key];
                var state:Object = data.controls[key];
                widget.visible = state != null && state.visible;
                widget.enabled = state != null && state.enabled;
                if (state == null) continue;
                if (state.options != null) {
                    // Do not close an open native menu on each room-status tick.
                    if (widget.dataProvider == null || widget["offlineOptionsKey"] != state.optionsKey) {
                        widget.dataProvider = new DataProvider(state.options);
                        widget["offlineOptionsKey"] = state.optionsKey;
                    }
                    if (widget.selectedIndex != state.index) widget.selectedIndex = state.index;
                } else {
                    widget.label = state.label;
                    widget.selected = state.selected;
                }
            }
            updating = false;
            placeRoom();
        }

        override public function updateStage(w:Number, h:Number):void {
            super.updateStage(w, h);
            queue = null;
            invalidate();
        }

        override protected function draw():void {
            super.draw();
            placeRoom();
        }

        private function findQueue(node:DisplayObjectContainer, depth:int = 0):Object {
            if (depth > 12) return null;
            for (var i:int = 0; i < node.numChildren; ++i) {
                var child:DisplayObject = node.getChildAt(i);
                if (getQualifiedClassName(child) == "BattleQueueUI") return child;
                if (child is DisplayObjectContainer) {
                    var found:Object = findQueue(child as DisplayObjectContainer, depth + 1);
                    if (found != null) return found;
                }
            }
            return null;
        }

        private function placeRoom():void {
            if (window == null || stage == null || window.parent == null) return;
            if (queue == null || queue.parent == null) queue = findQueue(App.stage as DisplayObjectContainer);
            var top:Number = stage.stageHeight * 0.24;
            var bottom:Number = stage.stageHeight * 0.80;
            if (queue != null) {
                var titleBounds:Rectangle = queue.modeTitle.getBounds(stage);
                var footerBounds:Rectangle = DisplayObject(queue.exitButton).getBounds(stage);
                top = titleBounds.bottom;
                bottom = footerBounds.top;
            }
            var frame:Rectangle = DisplayObject(window).getBounds(stage);
            var origin:Point = DisplayObject(window).localToGlobal(new Point());
            var globalPos:Point = new Point((stage.stageWidth - frame.width) / 2 - (frame.x - origin.x),
                top + (bottom - top - frame.height) / 2 - (frame.y - origin.y));
            var localPos:Point = window.parent.globalToLocal(globalPos);
            window.x = Math.round(localPos.x);
            window.y = Math.round(localPos.y);
        }

        override protected function onDispose():void {
            for (var key:String in widgets) {
                var widget:Object = widgets[key];
                widget.removeEventListener(ButtonEvent.CLICK, clicked);
                widget.removeEventListener(ListEvent.INDEX_CHANGE, selected);
                if (key == "tier" || key == "skill" || key == "size1" || key == "size2") widget.close();
                widget.dispose();
            }
            widgets = {}; fields = {}; queue = null; offlineAction = null;
            super.onDispose();
        }
    }
}
