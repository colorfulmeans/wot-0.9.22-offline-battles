package {
    import flash.display.DisplayObject;
    import flash.display.DisplayObjectContainer;
    import flash.events.Event;
    import flash.geom.Point;
    import flash.geom.Rectangle;
    import flash.text.TextField;
    import flash.text.TextFormat;
    import flash.utils.getQualifiedClassName;
    import net.wg.infrastructure.base.AbstractWindowView;
    import net.wg.gui.components.windows.Window;
    import scaleform.clik.core.UIComponent;
    import scaleform.clik.data.DataProvider;
    import scaleform.clik.events.ButtonEvent;
    import scaleform.clik.events.ListEvent;
    import scaleform.clik.utils.Padding;

    // Compiled against #1513; the builder gives this movie its own class name.
    public dynamic class TrainingWindow extends AbstractWindowView {
        public var offlineAction:Function;
        private var fields:Object = {};
        private var widgets:Object = {};
        private var icons:Object = {};
        private var updating:Boolean = false;
        private var queue:Object;
        private var bodyFormat:TextFormat;
        private var embedded:Boolean;
        private var reportedLayout:Boolean = false;

        public function TrainingWindow() { super(); }

        override protected function initialize():void {
            super.initialize();
            // The retained authoring prototype is not the content's geometry.
            // Window constraints capture scale before configUI runs.
            _originalWidth = 660;
            _originalHeight = 282;
            setActualScale(1, 1);
        }

        override protected function configUI():void {
            bodyFormat = this["battleType"].defaultTextFormat;
            embedded = this["battleType"].embedFonts;
            bodyFormat.size = 13;
            bodyFormat.color = 11711136;
            while (numChildren) removeChildAt(0);
            graphics.beginFill(0, 0);
            graphics.drawRect(0, 0, 660, 282);
            graphics.endFill();
            setSize(660, 282);
            super.configUI();
            text("room", 0, 2, 660);
            text("players", 0, 24, 660);
            text("tierLabel", 0, 47, 312);
            text("skillLabel", 336, 47, 324);
            dropdown("tier", 0, 65, 312);
            dropdown("skill", 336, 65, 324);
            button("map", "ButtonNormal", 0, 97, 504);
            button("random", "ButtonNormal", 516, 97, 144);
            text("size1Label", 0, 126, 312);
            text("size2Label", 336, 126, 324);
            dropdown("size1", 0, 144, 312);
            dropdown("size2", 336, 144, 324);
            var classes:Array = ["random", "lightTank", "mediumTank", "heavyTank", "AT-SPG", "SPG"];
            for (var side:int = 1; side <= 2; ++side) {
                for (var index:int = 0; index < classes.length; ++index) {
                    var xPos:Number = (side == 1 ? 0 : 336) + index * 52;
                    var key:String = "class_" + side + "_" + classes[index];
                    var check:Object = component(key, "CheckBox", xPos, 177, 52);
                    check.label = "";
                    check.addEventListener(ButtonEvent.CLICK, clicked);
                    if (classes[index] == "random") continue;
                    var icon:Object = App.utils.classFactory.getComponent("Image", UIComponent, null, loaderInfo);
                    icon.x = 24; icon.y = 1;
                    icon.source = "img://gui/maps/icons/vehicleTypes/" + classes[index] + ".png";
                    icon.enableInitCallback = false;
                    icon.mouseEnabled = false;
                    icons[key] = icon;
                    DisplayObjectContainer(check).addChild(icon as DisplayObject);
                }
            }
            button("team1", "ButtonNormal", 0, 215, 208);
            button("team_random", "ButtonNormal", 226, 215, 208);
            button("team2", "ButtonNormal", 452, 215, 208);
            text("message", 0, 240, 660);
            button("start", "ButtonRed", 378, 260, 180);
            button("close", "ButtonBlack", 566, 260, 94);
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
            var item:Object = App.utils.classFactory.getComponent(linkage, UIComponent, null, loaderInfo);
            item.name = key;
            item.x = xPos; item.y = yPos;
            // BlackButton.width rescales its internal state clips. setSize
            // bypasses that override and leaves a 160px face in a 94px slot.
            // Keep the other stock controls at their authored height too.
            if (linkage == "ButtonRed") item.height = 22;
            item.width = w;
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
            item.itemRenderer = "DropDownListItemRendererSound";
            item.autoSize = "none";
            item.focusable = true;
            item.menuDirection = "down";
            item.menuMargin = 1;
            item.menuOffset = new Padding(-5, 0, 0, 3);
            item.menuPadding = new Padding(0, 0, 0, 0);
            item.menuRowsFixed = false;
            item.rowCount = 8;
            item.menuWidth = -1;
            item.menuWrapping = "normal";
            item.scrollBar = "ScrollBar";
            item.thumbOffsetTop = 0;
            item.thumbOffsetBottom = 0;
            item.showEmptyItems = false;
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
            // Python population can precede CLIK's first render validation.
            // Build the fields before publishing data; otherwise the first
            // model is discarded and the wrapper measures only the prototype.
            validateNow();
            updating = true;
            window.title = data.title;
            window.useBottomBtns = true;
            for (var key:String in fields) fields[key].text = data.labels[key] == null ? "" : String(data.labels[key]);
            for (key in widgets) {
                var widget:Object = widgets[key];
                // A stock animated control must finish configUI before its
                // initial data/selection is applied.
                widget.validateNow();
                var state:Object = data.controls[key];
                widget.visible = state != null && state.visible;
                widget.enabled = state != null && state.enabled;
                if (icons[key] != null) icons[key].alpha = widget.enabled ? 1 : 0.45;
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
            // Window.updateSource caches content size. Re-measure after our
            // dynamic children exist, using the native padding/chrome contract.
            UIComponent(window).invalidate(Window.INVALID_SRC_VIEW);
            UIComponent(window).validateNow();
            updating = false;
            placeRoom();
            if (!reportedLayout && offlineAction != null) {
                reportedLayout = true;
                offlineAction("diagnostics", "content=" + width + "x" + height +
                    " actualScale=" + actualScaleX + "," + actualScaleY +
                    " frame=" + window.width + "x" + window.height +
                    " roomChars=" + TextField(fields["room"]).length +
                    " mapChars=" + String(widgets["map"].label).length);
                for (var role:String in widgets) {
                    var control:Object = widgets[role];
                    var bounds:Rectangle = DisplayObject(control).getBounds(this);
                    offlineAction("diagnostics", "control=" + role +
                        " logical=" + control.width + "x" + control.height +
                        " bounds=" + bounds.x + "," + bounds.y + "," + bounds.width + "," + bounds.height +
                        " scale=" + control.actualScaleX + "," + control.actualScaleY);
                }
            }
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
            // An open popup or a glowing button must not change the anchor.
            // Only the stock frame background defines the room rectangle.
            var frame:Rectangle = window.getBackground().getBounds(stage);
            var origin:Point = DisplayObject(window).localToGlobal(new Point());
            var globalPos:Point = new Point((stage.stageWidth - frame.width) / 2 - (frame.x - origin.x),
                top + (bottom - top - frame.height) / 2 - (frame.y - origin.y));
            var localPos:Point = window.parent.globalToLocal(globalPos);
            window.x = Math.round(localPos.x);
            window.y = Math.round(localPos.y);
        }

        override protected function onDispose():void {
            for each (var icon:Object in icons) icon.dispose();
            icons = {};
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
